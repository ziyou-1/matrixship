import importlib.util
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"
PIPELINE = ROOT / "backend" / "replacement_pipeline.py"


class _DummyQtMeta(type):
    def __getattr__(cls, _name):
        return 0


class _DummyQtObject(metaclass=_DummyQtMeta):
    def __init__(self, *args, **kwargs):
        self._value = ""

    def __call__(self, *args, **kwargs):
        return _DummyQtObject()

    def __getattr__(self, _name):
        return _DummyQtObject()

    def __or__(self, _other):
        return 0

    def __bool__(self):
        return False

    def __iter__(self):
        return iter(())

    def __int__(self):
        return 0

    def text(self):
        return self._value

    def setText(self, value):
        self._value = str(value or "")


class _FakeWidget:
    def __init__(self, value="", checked=False, data=None):
        self.value = value
        self.checked = checked
        self.data = data
        self.enabled = None
        self.visible = None
        self.pixmap = None
        self.tool_tip = ""

    def setText(self, value):
        self.value = str(value or "")

    def text(self):
        return self.value

    def setEnabled(self, value):
        self.enabled = bool(value)

    def setVisible(self, value):
        self.visible = bool(value)

    def isChecked(self):
        return bool(self.checked)

    def currentData(self):
        return self.data

    def currentIndex(self):
        return 0 if self.data is not None else -1

    def setValue(self, value):
        self.value = value

    def clear(self):
        self.value = ""
        self.pixmap = None

    def setToolTip(self, value):
        self.tool_tip = str(value or "")

    def setPixmap(self, value):
        self.pixmap = value

    def size(self):
        return _DummyQtObject()


class _FakeProgress(_FakeWidget):
    def __init__(self):
        super().__init__()
        self.range = None
        self.format = ""

    def setRange(self, start, end):
        self.range = (start, end)

    def setFormat(self, value):
        self.format = str(value or "")


class _FakeComboBox(_FakeWidget):
    def __init__(self):
        super().__init__()
        self.items = []
        self.index = -1

    def clear(self):
        self.items = []
        self.index = -1

    def addItem(self, label, data=None):
        self.items.append((str(label), data))
        if self.index < 0:
            self.index = 0

    def currentData(self):
        if 0 <= self.index < len(self.items):
            return self.items[self.index][1]
        return None

    def currentIndex(self):
        return self.index

    def setCurrentIndex(self, index):
        self.index = int(index)


class _FakeTable:
    def cellWidget(self, *_args):
        return None

    def item(self, *_args):
        return None

    def setRowCount(self, *_args):
        pass

    def rowCount(self):
        return 0


class _RecordingTable:
    def __init__(self):
        self.rows = []

    def setRowCount(self, count):
        self.rows = self.rows[:int(count or 0)]

    def rowCount(self):
        return len(self.rows)

    def insertRow(self, row):
        self.rows.insert(int(row), {})

    def setItem(self, row, column, item):
        self.rows[int(row)][int(column)] = item


class _DummySignal:
    def __init__(self, *args, **kwargs):
        self.calls = []

    def connect(self, *args, **kwargs):
        self.calls.append(("connect", args, kwargs))

    def emit(self, *args, **kwargs):
        self.calls.append(("emit", args, kwargs))


class _DummyQtNamespace:
    def __getattr__(self, _name):
        return 0


class _DummyQtModule(types.ModuleType):
    def __getattr__(self, name):
        if name == "Signal":
            return lambda *args, **kwargs: _DummySignal(*args, **kwargs)
        if name == "Qt":
            return _DummyQtNamespace()
        return _DummyQtObject


def install_qt_stubs():
    pyside = types.ModuleType("PySide6")
    qtcore = _DummyQtModule("PySide6.QtCore")
    qtgui = _DummyQtModule("PySide6.QtGui")
    qtwidgets = _DummyQtModule("PySide6.QtWidgets")
    pyside.QtCore = qtcore
    pyside.QtGui = qtgui
    pyside.QtWidgets = qtwidgets
    sys.modules.update({
        "PySide6": pyside,
        "PySide6.QtCore": qtcore,
        "PySide6.QtGui": qtgui,
        "PySide6.QtWidgets": qtwidgets,
    })


def qt_runtime_available():
    try:
        return importlib.util.find_spec("PySide6") is not None and importlib.util.find_spec("shiboken6.Shiboken") is not None
    except Exception:
        return False


def load_client():
    if not qt_runtime_available():
        install_qt_stubs()
    else:
        try:
            from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
        except Exception:
            install_qt_stubs()
    spec = importlib.util.spec_from_file_location("matrix_native_client_for_replacement_v2", CLIENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_replacement_pipeline():
    spec = importlib.util.spec_from_file_location("replacement_pipeline_for_video_replacement", PIPELINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SERVICE = ROOT / "backend" / "replacement_service.py"


def load_replacement_service():
    spec = importlib.util.spec_from_file_location("replacement_service_for_video_replacement_v2", SERVICE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _recording_bridge():
    events = []
    bridge = types.SimpleNamespace(payload=types.SimpleNamespace(
        emit=lambda tag, payload: events.append((tag, payload))
    ))
    return bridge, events


class _AdapterFakeSourceResolver:
    def prepare(self, job, request, progress=None):
        job["sourceVideoPath"] = os.path.join(job["outDir"], "source.mp4")
        Path(job["sourceVideoPath"]).write_bytes(b"fake-video")
        job["breakdownAnalysis"] = {"meta": {"duration": 8.0}}
        return job


class _AdapterFakePipeline:
    def build_plan(self, job):
        job["segments"] = [{"index": 1, "start": 0.0, "end": 8.0, "status": "planned"}]
        return job

    def execute(self, job, selected_segments=None, progress=None):
        segment = job["segments"][0]
        output = os.path.join(job["outDir"], "segment-01.mp4")
        Path(output).write_bytes(b"fake-output")
        segment.update({"status": "done", "videoPath": output, "qcStatus": "passed"})
        job["status"] = "awaiting_review"
        return job

    def concat(self, job):
        output = os.path.join(job["outDir"], "final.mp4")
        Path(output).write_bytes(b"fake-final")
        job.update({"status": "completed", "outputPath": output})
        return job

    def retry(self, job, segment_indices, progress=None):
        return job


def fake_qt_multimedia_backend():
    from PySide6.QtMultimediaWidgets import QGraphicsVideoItem

    multimedia = types.ModuleType("PySide6.QtMultimedia")
    multimedia_widgets = types.ModuleType("PySide6.QtMultimediaWidgets")

    class FakeQMediaPlayer:
        instances = []

        class Loops:
            Infinite = -1
            Once = 1

        class PlaybackState:
            StoppedState = 0
            PlayingState = 1
            PausedState = 2

        PlayingState = PlaybackState.PlayingState

        def __init__(self, _parent=None):
            self.__class__.instances.append(self)
            self.positionChanged = _DummySignal()
            self.durationChanged = _DummySignal()
            self.playbackStateChanged = _DummySignal()
            self.loops = None
            self.source = None
            self.play_calls = 0
            self.stop_calls = 0
            self.deleted = False
            self.state = self.PlaybackState.StoppedState

        def setAudioOutput(self, output):
            self.audio_output = output

        def setVideoOutput(self, output):
            self.video_output = output

        def setLoops(self, loops):
            self.loops = loops

        def setSource(self, source):
            self.source = source

        def setPosition(self, position):
            self.position = position

        def playbackState(self):
            return self.state

        def play(self):
            self.play_calls += 1
            self.state = self.PlaybackState.PlayingState

        def pause(self):
            self.state = self.PlaybackState.PausedState

        def stop(self):
            self.stop_calls += 1
            self.state = self.PlaybackState.StoppedState

        def deleteLater(self):
            self.deleted = True

    class FakeQAudioOutput:
        instances = []

        def __init__(self, _parent=None):
            self.__class__.instances.append(self)
            self.volume = 1.0
            self.muted = False
            self.deleted = False

        def setVolume(self, value):
            self.volume = float(value)

        def setMuted(self, value):
            self.muted = bool(value)

        def isMuted(self):
            return self.muted

        def deleteLater(self):
            self.deleted = True

    multimedia.QMediaPlayer = FakeQMediaPlayer
    multimedia.QAudioOutput = FakeQAudioOutput
    multimedia_widgets.QGraphicsVideoItem = QGraphicsVideoItem
    return {
        "PySide6.QtMultimedia": multimedia,
        "PySide6.QtMultimediaWidgets": multimedia_widgets,
    }, FakeQMediaPlayer, FakeQAudioOutput


def make_tone_video(client, path, duration=1.0, frequency=880):
    cmd = [
        client._ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=blue:s=160x284:r=30:d=%s" % duration,
        "-f", "lavfi", "-i", "sine=frequency=%s:sample_rate=48000:duration=%s" % (frequency, duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-shortest", str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def mean_volume_db(client, path):
    completed = subprocess.run(
        [client._ffmpeg_exe(), "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", completed.stderr or "")
    return float(match.group(1)) if match else float("-inf")


class VideoReplacementV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_client()
        cls.pipeline_module = load_replacement_pipeline()

    def test_mix_clips_preserves_non_silent_audio_when_requested(self):
        with tempfile.TemporaryDirectory() as td:
            first = Path(td) / "first.mp4"
            second = Path(td) / "second.mp4"
            output = Path(td) / "output.mp4"
            make_tone_video(self.client, first, frequency=440)
            make_tone_video(self.client, second, frequency=880)

            self.client.mix_clips(
                [str(first), str(second)],
                str(output),
                preserve_source_audio=True,
            )

            validation = self.client.validate_video_file(str(output))
            self.assertTrue(validation["ok"])
            self.assertTrue(validation["hasAudio"])
            self.assertGreater(mean_volume_db(self.client, output), -45.0)

    def test_content_search_table_shows_metrics_after_link(self):
        page = self.client.ContentPage.__new__(self.client.ContentPage)
        page._results = []
        page.table = _RecordingTable()
        page.status = _FakeWidget()
        page.b_search = _FakeWidget()

        page._on("c_search", {
            "status": "done",
            "result": {
                "items": [{
                    "title": "卫浴花洒",
                    "nickname": "万沐合",
                    "work_url": "https://www.douyin.com/video/123",
                    "digg_count": 1234,
                    "collect_count": 78,
                    "share_count": 56,
                    "duration": 83,
                }]
            },
        })

        self.assertEqual(page.table.rows[0][0].text(), "卫浴花洒")
        self.assertEqual(page.table.rows[0][2].text(), "https://www.douyin.com/video/123")
        self.assertEqual(page.table.rows[0][3].text(), "1234")
        self.assertEqual(page.table.rows[0][4].text(), "78")
        self.assertEqual(page.table.rows[0][5].text(), "1分23秒")

    def test_content_search_table_header_uses_collect_count(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class ContentPage")
        init_start = src.index("    def __init__(self):", start)
        init_end = src.index("    def _pf(self):", init_start)
        init_src = src[init_start:init_end]

        self.assertIn('"收藏数"', init_src)
        self.assertNotIn('"转发数"', init_src)

    def test_xhs_collection_actions_explain_visible_browser(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class ContentPage")
        search_start = src.index("    def search(self):", start)
        download_start = src.index("    def download(self):", search_start)
        breakdown_start = src.index("    def breakdown(self):", download_start)
        search_src = src[search_start:download_start]
        download_src = src[download_start:breakdown_start]

        self.assertIn("账号采集中", search_src)
        self.assertIn("小红书账号", search_src)
        self.assertIn("账号下载中", download_src)
        self.assertIn("小红书账号", download_src)


    def test_xhs_content_search_offline_error_names_xhs_not_douyin(self):
        page = self.client.ContentPage.__new__(self.client.ContentPage)
        page._results = []
        page.table = _RecordingTable()
        page.status = _FakeWidget()
        page.b_search = _FakeWidget()
        page._pf = lambda: "xhs"

        page._on("c_search", {
            "status": "failed",
            "error": "local_browser_offline",
            "type": "xhs.search",
        })

        self.assertIn("小红书", page.status.text())
        self.assertNotIn("抖音账号", page.status.text())

    def test_source_audio_mux_replaces_generated_audio_with_original_segment(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.mp4"
            edited = Path(td) / "edited.mp4"
            make_tone_video(self.client, source, duration=0.7, frequency=440)
            make_tone_video(self.client, edited, duration=1.5, frequency=880)

            result = self.client._replace_segment_audio_from_source(str(source), str(edited))
            validation = self.client.validate_video_file(result)

        self.assertEqual(result, str(edited))
        self.assertTrue(validation["ok"])
        self.assertTrue(validation["hasAudio"])
        self.assertLess(validation["duration"], 1.0)

    def test_tts_audio_mode_replaces_segment_audio_without_source_mux(self):
        segment = {
            "index": 1,
            "segmentType": "non_talking",
            "duration": 8,
            "script": "新的口播配音",
            "sourceSegmentPath": "/tmp/source-segment.mp4",
        }
        job = {
            "outDir": "/tmp/job",
            "audioMode": "tts",
            "voiceId": "Zephyr",
            "principalReplacementMode": "source_video_edit",
            "principalActor": {"status": "detected", "description": "main presenter"},
            "personReferenceUrls": ["https://x/person.jpg"],
        }

        with mock.patch.object(
                self.client, "upload_asset_url",
                return_value=("https://x/source.mp4", {"id": "source-temp"})), \
                mock.patch.object(self.client, "lk888_media_task", return_value="https://x/edited.mp4"), \
                mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: path), \
                mock.patch.object(self.client, "_replace_segment_audio_from_source") as replace_source_audio, \
                mock.patch.object(self.client, "_ensure_segment_audio") as ensure_audio, \
                mock.patch.object(self.client, "_replace_replacement_segment_audio_with_tts", create=True,
                                  side_effect=lambda _job, _segment, path: path) as replace_tts_audio, \
                mock.patch.object(self.client, "_run_replacement_segment_qc", return_value={
                    "ok": True, "frames": ["a.jpg"], "checks": {"media": "passed", "audio": "passed"},
                }), \
                mock.patch.object(self.client, "_save_replacement_job"):
            path = self.client._run_hybrid_non_talking_segment(job, segment)

        replace_tts_audio.assert_called_once_with(job, segment, "/tmp/job/edited_01.mp4")
        replace_source_audio.assert_not_called()
        ensure_audio.assert_not_called()
        self.assertEqual(path, "/tmp/job/edited_01.mp4")

    def test_tts_duration_preflight_flags_segment_script_that_will_be_cut(self):
        long_script = (
            "这是一段明显超过八秒的中文口播内容，需要在很短的片段里讲完很多卖点和行动引导，"
            "还要继续补充优惠政策、金融方案、到店礼和试驾预约提醒。"
        )
        with mock.patch.dict(os.environ, {"VIDEO_REPLACE_TTS_MAX_SPEED": "1.45"}, clear=False):
            issues = self.client._replacement_tts_timing_issues(
                [{"index": 1, "duration": 8, "script": long_script}],
                "tts",
            )

        self.assertEqual(issues[0]["index"], 1)
        self.assertGreater(issues[0]["estimatedSec"], 8 * 1.45)
        self.assertIn("超过自动提速上限", self.client._format_replacement_tts_timing_block_message(issues))

    def test_tts_audio_mode_speeds_up_real_audio_to_fit_segment_before_mux(self):
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "segment.mp4"
            video.write_bytes(b"placeholder")
            job = {"outDir": td, "audioMode": "tts", "voiceId": "Zephyr"}
            segment = {"index": 1, "duration": 8, "script": "一段生成后过长的口播"}

            speeded = Path(td) / "replacement_tts_01.fit.mp3"
            with mock.patch.object(self.client, "lk888_tts_voice", return_value="https://cdn.example.com/voice.mp3"), \
                    mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: Path(path).write_bytes(b"mp3")), \
                    mock.patch.object(self.client, "_probe_video", return_value={"duration": 8.0}), \
                    mock.patch.object(self.client, "_probe_media_duration", return_value=10.0), \
                    mock.patch.object(self.client, "_speed_up_audio", side_effect=lambda src, dst, speed: Path(dst).write_bytes(b"fit") or str(speeded)) as speed_up, \
                    mock.patch.object(self.client, "_replace_video_audio", side_effect=lambda _video, _audio, out, require_full_audio=False: Path(out).write_bytes(b"mp4") or out) as replace_video_audio:
                self.client._replace_replacement_segment_audio_with_tts(job, segment, str(video))

        speed_up.assert_called_once()
        self.assertAlmostEqual(speed_up.call_args.args[2], 1.25)
        self.assertEqual(segment["ttsTimingStatus"], "sped_up")
        self.assertEqual(segment["ttsSpeed"], 1.25)
        self.assertEqual(segment["ttsOriginalDurationSec"], 10.0)
        self.assertTrue(replace_video_audio.call_args.args[1].endswith(".fit.mp3"))

    def test_tts_audio_mode_rejects_real_audio_beyond_speed_limit_before_mux(self):
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "segment.mp4"
            video.write_bytes(b"placeholder")
            job = {"outDir": td, "audioMode": "tts", "voiceId": "Zephyr"}
            segment = {"index": 1, "duration": 8, "script": "一段生成后极长的口播"}

            with mock.patch.dict(os.environ, {"VIDEO_REPLACE_TTS_MAX_SPEED": "1.45"}, clear=False), \
                    mock.patch.object(self.client, "lk888_tts_voice", return_value="https://cdn.example.com/voice.mp3"), \
                    mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: Path(path).write_bytes(b"mp3")), \
                    mock.patch.object(self.client, "_probe_video", return_value={"duration": 8.0}), \
                    mock.patch.object(self.client, "_probe_media_duration", return_value=12.0), \
                    mock.patch.object(self.client, "_speed_up_audio") as speed_up, \
                    mock.patch.object(self.client, "_replace_video_audio") as replace_video_audio:
                with self.assertRaisesRegex(RuntimeError, "replacement_tts_audio_too_long"):
                    self.client._replace_replacement_segment_audio_with_tts(job, segment, str(video))

        speed_up.assert_not_called()
        replace_video_audio.assert_not_called()

    def test_global_dark_theme_keeps_form_controls_legible(self):
        qss = self.client.build_qss(self.client.THEMES["dark"])

        self.assertIn("QCheckBox::indicator", qss)
        self.assertIn("image:url", qss)
        self.assertIn("QPlainTextEdit", qss)
        self.assertIn("selection-color", qss)
        self.assertIn("QTableWidget::item:selected", qss)
        self.assertIn("QPushButton#ghost", qss)
        self.assertIn("min-width", qss)

    def test_replacement_segment_table_uses_readable_script_editor_and_fixed_actions(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn("self.table.setWordWrap(True)", src)
        self.assertIn("self.table.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)", src)
        self.assertIn("self.table.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)", src)
        self.assertIn("self.table.verticalScrollBar().setSingleStep(24)", src)
        self.assertIn("self.table.verticalScrollBar().setPageStep(122)", src)
        self.assertIn("self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)", src)
        self.assertIn("self.table.setColumnWidth(2, 520)", src)
        self.assertIn("self.table.verticalHeader().setDefaultSectionSize(122)", src)
        self.assertIn("self.table.setColumnWidth(8, 120)", src)
        self.assertIn("def _make_segment_script_editor(self, seg):", src)
        self.assertIn("editor = QtWidgets.QPlainTextEdit()", src)
        self.assertIn("editor.textChanged.connect", src)
        self.assertIn("editor.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)", src)
        self.assertIn("editor.setMinimumHeight(104)", src)
        self.assertIn('delete_btn = _round_icon_btn(', src)
        self.assertIn('"trash", 30', src)
        self.assertIn("def _segment_script_value(self, row):", src)
        self.assertIn("def _sync_segment_scripts_from_table(self):", src)
        self.assertIn("self._sync_segment_scripts_from_table()", src)

    def test_replacement_segment_actions_use_compact_icon_buttons(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("def refresh_segments(self):")
        end = src.index("    def open_output(self):", start)
        block = src[start:end]

        self.assertIn("regen_btn = _round_icon_btn(", block)
        self.assertIn('"refresh", 30', block)
        self.assertIn('delete_btn = _round_icon_btn(', block)
        self.assertIn('"trash", 30', block)
        self.assertIn('tip="重新生成视频"', block)
        self.assertIn('tip="删除"', block)
        self.assertNotIn('QtWidgets.QPushButton("重生")', block)
        self.assertNotIn('QtWidgets.QPushButton("删除")', block)
        self.assertNotIn("setFixedSize(72, 30)", block)
        self.assertNotIn("setFixedSize(92, 30)", block)
        self.assertIn("action_layout.setSpacing(4)", block)

    def test_replacement_audio_selector_uses_auto_instead_of_source_sound(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("self.audio_mode = QtWidgets.QComboBox()")
        end = src.index("self.replacement_voice = QtWidgets.QComboBox()", start)
        block = src[start:end]

        self.assertIn('self.audio_mode.addItem("自动", "auto")', block)
        self.assertNotIn('self.audio_mode.addItem("原片声音", "source")', block)
        self.assertNotIn("默认保留原片声音", block)

    def test_comic_segment_table_uses_two_frame_columns_without_editor_overflow(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn(
            '["序号", "口播稿", "首帧图", "尾帧图", "视频", "操作"]',
            src,
        )
        self.assertNotIn(
            '["序号", "口播稿", "流程图生成", "视频", "操作"]',
            src,
        )
        editor_start = src.index("def _make_segment_script_editor(self, seg):")
        editor_end = src.index("def _segment_script_value(self, row):", editor_start)
        editor_block = src[editor_start:editor_end]
        self.assertNotIn("editor.setMinimumWidth(500)", editor_block)
        self.assertIn("def _make_comic_frame_cell(self, segment, frame_kind):", src)
        self.assertIn("setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)", src)

    def test_comic_frame_click_opens_local_preview_not_public_url(self):
        src = CLIENT.read_text(encoding="utf-8")
        block = src[src.index("def _make_comic_frame_cell"):src.index("def _make_segment_script_editor")]

        self.assertIn("_open_comic_frame_preview", block)
        self.assertNotIn("_open_url", block)
        self.assertNotIn("QDesktopServices", block)

    def test_comic_frame_cells_have_independent_regenerate_buttons(self):
        src = CLIENT.read_text(encoding="utf-8")
        block = src[src.index("def _make_comic_frame_cell"):src.index("def _make_segment_script_editor")]

        self.assertIn('regenerate_comic_frame(row, "start")', block)
        self.assertIn('regenerate_comic_frame(row, "end")', block)
        self.assertIn('_round_icon_btn("refresh"', block)

    @unittest.skipUnless(qt_runtime_available(), "PySide6 runtime unavailable")
    def test_comic_row_regeneration_buttons_dispatch_clicks_while_busy(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtTest import QTest

        app = self.client.QtWidgets.QApplication.instance() or self.client.QtWidgets.QApplication([])
        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        segment = {"index": 1, "status": "pending"}
        page._job = {"replacementMode": "comic_project", "segments": [segment]}
        page._busy = True
        page._comic_frame_downloads = {}
        page._comic_video_cells = []
        page.table = self.client.QtWidgets.QTableWidget()
        page.regenerate_comic_frame = mock.Mock()
        page.regenerate_selected_segment = mock.Mock()
        page.delete_segment = mock.Mock()

        start_cell = page._make_comic_frame_cell(segment, "start")
        end_cell = page._make_comic_frame_cell(segment, "end")
        start_button = start_cell.findChildren(self.client.QtWidgets.QPushButton)[0]
        end_button = end_cell.findChildren(self.client.QtWidgets.QPushButton)[0]
        self.assertTrue(start_button.isEnabled())
        self.assertTrue(end_button.isEnabled())
        QTest.mouseClick(start_button, self.client.QtCore.Qt.LeftButton)
        QTest.mouseClick(end_button, self.client.QtCore.Qt.LeftButton)

        page.refresh_segments()
        action_cell = page.table.cellWidget(0, 5)
        video_button = [
            button for button in action_cell.findChildren(self.client.QtWidgets.QPushButton)
            if button.isEnabled()
        ][0]
        self.assertTrue(video_button.isEnabled())
        QTest.mouseClick(video_button, self.client.QtCore.Qt.LeftButton)
        app.processEvents()

        page.regenerate_comic_frame.assert_has_calls([mock.call(0, "start"), mock.call(0, "end")])
        page.regenerate_selected_segment.assert_called_once_with()
        page._release_comic_video_cells()

    def test_comic_missing_frame_uses_authenticated_background_download(self):
        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn("def _request_comic_frame_download", src)
        start = src.index("def _request_comic_frame_download")
        block = src[start:src.index("def _make_comic_frame_cell", start)]

        self.assertIn("ComicProjectAdapter()", block)
        self.assertIn("_comic_download_frame_image", block)
        self.assertIn("run_bg(work)", block)
        self.assertIn('"downloading"', block)
        self.assertIn('"errorId"', block)
        self.assertNotIn("requests.get", block)
        self.assertNotIn("_open_url", block)

    def test_comic_video_column_uses_inline_player_not_url_text(self):
        src = CLIENT.read_text(encoding="utf-8")
        block = src[src.index("def refresh_segments(self):"):src.index("def open_output(self):")]

        self.assertIn("_make_comic_video_cell(seg)", block)
        self.assertNotIn('or seg.get("videoUrl")', block)
        self.assertNotIn("QTableWidgetItem(video_text)", block)

    def test_comic_inline_player_does_not_autoplay(self):
        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn("class ComicSegmentVideoCell", src)
        start = src.index("class ComicSegmentVideoCell")
        block = src[start:src.index("class ", start + 10)]

        self.assertIn("autoplay=False", block)
        self.assertNotIn("self.player.play()", block)

    def test_comic_inline_player_has_local_controls_and_stable_size(self):
        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn("class ComicSegmentVideoCell", src)
        start = src.index("class ComicSegmentVideoCell")
        block = src[start:src.index("class ", start + 10)]

        self.assertIn("setFixedSize", block)
        self.assertIn("positionChanged.connect", block)
        self.assertIn("durationChanged.connect", block)
        self.assertIn("sliderMoved.connect", block)
        self.assertIn("setVolume", block)
        self.assertIn("_open_preview", block)
        self.assertNotIn("_toggle_fullscreen", block)
        self.assertNotIn("showFullScreen", block)
        for icon in ('"play"', '"pause"', '"volume"', '"fullscreen"'):
            self.assertIn(icon, block)
        self.assertNotIn("videoUrl", block)

    def test_comic_missing_media_states_are_distinct_and_use_readable_text(self):
        src = CLIENT.read_text(encoding="utf-8")
        self.assertIn("def _comic_video_cell_state", src)
        start = src.index("def _comic_video_cell_state")
        block = src[start:src.index("class ComicSegmentVideoCell", start)]

        self.assertIn('"待生成"', block)
        self.assertIn('"待重新生成"', block)
        self.assertIn('"正在获取视频"', block)
        self.assertIn('"获取失败，请重试。"', block)
        self.assertIn('"video_stale"', block)
        self.assertIn('"downloading"', block)

    def test_video_player_box_set_media_preserves_legacy_play_behavior(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("class VideoPlayerBox")
        block = src[start:src.index("# ---------- theme ----------", start)]

        self.assertIn("def set_media(self, path, autoplay=False, loop=False):", block)
        self.assertIn("self._ensure_player(loop=loop)", block)
        self.assertIn("self.set_media(path, autoplay=True, loop=True)", block)

    def test_comic_refresh_and_destruction_release_old_players(self):
        src = CLIENT.read_text(encoding="utf-8")
        refresh = src[src.index("def refresh_segments(self):"):src.index("def open_output(self):")]
        page = src[src.index("class VideoReplacementPage"):src.index("class ", src.index("class VideoReplacementPage") + 10)]

        self.assertIn("_release_comic_video_cells()", refresh)
        self.assertIn("def closeEvent(self, event):", page)
        self.assertIn("_release_comic_video_cells()", page)

    def test_comic_regeneration_confirmations_are_plain(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("def regenerate_comic_frame")
        end = src.index("def _run_comic_frame_regeneration", start)
        frame_block = src[start:end]
        video_start = src.index("def regenerate_selected_segment")
        video_end = src.index("def delete_segment", video_start)
        video_block = src[video_start:video_end]
        combined = frame_block + video_block

        self.assertIn("确定重新生成片段 %s 的%s吗？", frame_block)
        self.assertIn("确定重新生成片段 %s 的视频吗？", video_block)
        for forbidden in ("费用", "任务数量", "预计金额", "云豆"):
            self.assertNotIn(forbidden, combined)

    @unittest.skipUnless(qt_runtime_available(), "PySide6 runtime unavailable")
    def test_comic_image_preview_dialog_constructs_offscreen_and_scales_local_image(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = self.client.QtWidgets.QApplication.instance() or self.client.QtWidgets.QApplication([])
        self.assertTrue(hasattr(self.client, "ComicImagePreviewDialog"))
        with tempfile.TemporaryDirectory() as td:
            image_path = str(Path(td) / "preview.png")
            image = self.client.QtGui.QImage(640, 360, self.client.QtGui.QImage.Format_RGB32)
            image.fill(self.client.QtGui.QColor("#336699"))
            self.assertTrue(image.save(image_path))

            dialog = self.client.ComicImagePreviewDialog(image_path)
            dialog.resize(360, 280)
            dialog.show()
            app.processEvents()
            pixmap = dialog.image_label.pixmap()

            self.assertFalse(pixmap.isNull())
            self.assertLessEqual(pixmap.width(), dialog.image_label.width())
            self.assertLessEqual(pixmap.height(), dialog.image_label.height())
            self.assertTrue(dialog.close())

    @unittest.skipUnless(qt_runtime_available(), "PySide6 runtime unavailable")
    def test_comic_video_preview_dialog_is_bounded_modal_and_releases_player(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = self.client.QtWidgets.QApplication.instance() or self.client.QtWidgets.QApplication([])
        modules, fake_player, fake_audio = fake_qt_multimedia_backend()
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "preview.mp4")
            Path(path).write_bytes(b"video-placeholder")
            with mock.patch.dict(sys.modules, modules), \
                    mock.patch.object(
                        self.client, "validate_video_file", return_value={"ok": True, "code": "ok"}
                    ):
                self.client._clear_comic_video_validation_cache()
                dialog = self.client.ComicVideoPreviewDialog(path)
                dialog.show()
                app.processEvents()
                available = self.client.QtGui.QGuiApplication.primaryScreen().availableGeometry()
                player = fake_player.instances[-1]
                audio = fake_audio.instances[-1]

                self.assertTrue(dialog.isModal())
                self.assertFalse(dialog.isFullScreen())
                self.assertLessEqual(dialog.width(), int(available.width() * 0.82))
                self.assertLessEqual(dialog.height(), int(available.height() * 0.82))
                self.assertEqual(dialog.video_box.current_path, path)
                self.assertEqual(player.play_calls, 0)
                self.assertTrue(dialog.close())
                app.processEvents()

        self.assertTrue(player.deleted)
        self.assertTrue(audio.deleted)
        self.assertIsNone(dialog.video_box.current_path)

    @unittest.skipUnless(qt_runtime_available(), "PySide6 runtime unavailable")
    def test_comic_video_surface_click_opens_preview_dialog(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtTest import QTest

        app = self.client.QtWidgets.QApplication.instance() or self.client.QtWidgets.QApplication([])
        modules, _fake_player, _fake_audio = fake_qt_multimedia_backend()
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "segment.mp4")
            Path(path).write_bytes(b"video-placeholder")
            segment = {"index": 1, "status": "done", "videoPath": path}
            with mock.patch.dict(sys.modules, modules), \
                    mock.patch.object(
                        self.client, "validate_video_file", return_value={"ok": True, "code": "ok"}
                    ), \
                    mock.patch.object(self.client, "ComicVideoPreviewDialog") as preview_dialog:
                self.client._clear_comic_video_validation_cache()
                cell = self.client.ComicSegmentVideoCell(segment)
                cell.show()
                app.processEvents()
                QTest.mouseClick(cell.video_box, self.client.QtCore.Qt.LeftButton)
                app.processEvents()

                preview_dialog.assert_called_once_with(path, cell)
                preview_dialog.return_value.exec.assert_called_once_with()
                cell.close()
                app.processEvents()

    def test_comic_video_state_validates_and_caches_local_media(self):
        self.assertTrue(hasattr(self.client, "_clear_comic_video_validation_cache"))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "segment.mp4"
            path.write_bytes(b"video-placeholder")
            segment = {"index": 1, "status": "done", "videoPath": str(path)}
            self.client._clear_comic_video_validation_cache()
            with mock.patch.object(
                    self.client, "validate_video_file",
                    return_value={"ok": True, "code": "ok"}) as validate:
                first = self.client._comic_video_cell_state(segment)
                second = self.client._comic_video_cell_state(segment)

        self.assertEqual(first, ("ready", ""))
        self.assertEqual(second, first)
        validate.assert_called_once_with(str(path))

    def test_comic_video_state_rejects_invalid_local_media_with_error_id(self):
        self.assertTrue(hasattr(self.client, "_clear_comic_video_validation_cache"))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "not-video.mp4"
            path.write_bytes(b"not a video")
            segment = {"index": 7, "status": "done", "videoPath": str(path)}
            self.client._clear_comic_video_validation_cache()
            with mock.patch.object(
                    self.client, "validate_video_file",
                    return_value={"ok": False, "code": "media_missing_video_stream"}) as validate, \
                    mock.patch.object(
                        self.client, "_replacement_error_id", return_value="err-invalid-media"
                    ) as error_id:
                first = self.client._comic_video_cell_state(segment)
                second = self.client._comic_video_cell_state(segment)

        self.assertEqual(first, ("invalid_media", "视频无效，请重试或查看日志。"))
        self.assertEqual(second, first)
        validate.assert_called_once_with(str(path))
        error_id.assert_called_once()
        self.assertNotIn("path", error_id.call_args.kwargs)
        self.assertNotIn("url", error_id.call_args.kwargs)
        self.assertNotIn("token", error_id.call_args.kwargs)

    def test_comic_video_state_keeps_valid_previous_video_playable_after_frame_failure(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "previous.mp4"
            path.write_bytes(b"video-placeholder")
            segment = {
                "index": 3,
                "status": "failed",
                "error": "comic_frame_regeneration_failed",
                "errorId": "err-frame",
                "videoPath": str(path),
            }
            self.client._clear_comic_video_validation_cache()
            with mock.patch.object(
                    self.client, "validate_video_file",
                    return_value={"ok": True, "code": "ok"}) as validate:
                state = self.client._comic_video_cell_state(segment)

        self.assertEqual(state, ("ready", ""))
        validate.assert_called_once_with(str(path))

    def test_comic_video_state_distinguishes_generation_from_download(self):
        with mock.patch.object(self.client, "validate_video_file") as validate:
            self.assertEqual(
                self.client._comic_video_cell_state({"status": "running", "stage": "comic_generate_video"}),
                ("generating", "正在生成视频"),
            )
            self.assertEqual(
                self.client._comic_video_cell_state({"status": "generating_video"}),
                ("generating", "正在生成视频"),
            )
            self.assertEqual(
                self.client._comic_video_cell_state({"status": "running", "stage": "downloading_video"}),
                ("downloading", "正在获取视频"),
            )
        validate.assert_not_called()

    def test_comic_frame_download_strict_mode_reraises_original_exception(self):
        self.assertIn(
            "raise_on_error",
            inspect.signature(self.client._comic_download_frame_image).parameters,
        )
        original = RuntimeError("original-frame-download-error")
        adapter = mock.Mock()
        adapter.download_media.side_effect = original
        segment = {"index": 1, "startFramePath": "previous.png"}
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "_comic_media_log"):
            with self.assertRaises(RuntimeError) as raised:
                self.client._comic_download_frame_image(
                    {"outDir": td}, segment, "start", "https://media.example/frame.png",
                    adapter, raise_on_error=True,
                )

        self.assertIs(raised.exception, original)
        self.assertEqual(segment["startFramePath"], "previous.png")

    def test_comic_frame_download_default_keeps_legacy_fallback(self):
        adapter = mock.Mock()
        adapter.download_media.side_effect = RuntimeError("legacy-download-error")
        segment = {"index": 1, "startFramePath": "previous.png"}
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "_comic_media_log"):
            result = self.client._comic_download_frame_image(
                {"outDir": td}, segment, "start", "https://media.example/frame.png", adapter
            )

        self.assertEqual(result, "previous.png")

    def test_comic_ui_frame_download_logs_original_exception_without_sensitive_context(self):
        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._comic_frame_downloads = {}
        page._job = {"id": "job-frame-download", "outDir": tempfile.gettempdir()}
        segment = {"index": 2, "startFrameUrl": "https://media.example/private/frame.png"}
        original = RuntimeError("original-adapter-error")
        bridge = types.SimpleNamespace(payload=_DummySignal())
        with mock.patch.object(self.client, "ComicProjectAdapter", return_value=mock.Mock()), \
                mock.patch.object(
                    self.client, "_comic_download_frame_image", side_effect=original
                ) as download, \
                mock.patch.object(
                    self.client, "_replacement_error_id", return_value="err-frame-download"
                ) as error_id, \
                mock.patch.object(self.client, "BRIDGE", bridge), \
                mock.patch.object(self.client, "run_bg", side_effect=lambda work: work()):
            page._request_comic_frame_download(segment, "start")

        self.assertTrue(download.call_args.kwargs.get("raise_on_error"))
        self.assertIs(error_id.call_args.args[1], original)
        self.assertTrue({"url", "token", "path"}.isdisjoint(error_id.call_args.kwargs))

    @unittest.skipUnless(qt_runtime_available(), "PySide6 runtime unavailable")
    def test_video_player_box_runtime_non_autoplay_and_legacy_loop(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self.assertTrue(hasattr(self.client, "_clear_comic_video_validation_cache"))
        app = self.client.QtWidgets.QApplication.instance() or self.client.QtWidgets.QApplication([])
        modules, fake_player, _fake_audio = fake_qt_multimedia_backend()
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "valid.mp4")
            Path(path).write_bytes(b"video-placeholder")
            with mock.patch.dict(sys.modules, modules), \
                    mock.patch.object(
                        self.client, "validate_video_file", return_value={"ok": True, "code": "ok"}
                    ):
                self.client._clear_comic_video_validation_cache()
                box = self.client.VideoPlayerBox(160, 90)
                self.assertTrue(box.set_media(path, autoplay=False, loop=False))
                player = fake_player.instances[-1]
                self.assertEqual(player.play_calls, 0)
                self.assertEqual(player.loops, fake_player.Loops.Once)
                self.assertTrue(box.play(path))
                self.assertEqual(player.play_calls, 1)
                self.assertEqual(player.loops, fake_player.Loops.Infinite)
                box.release()
                app.processEvents()

    @unittest.skipUnless(qt_runtime_available(), "PySide6 runtime unavailable")
    def test_video_player_box_runtime_release_clears_backend_resources(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self.assertTrue(hasattr(self.client, "_clear_comic_video_validation_cache"))
        app = self.client.QtWidgets.QApplication.instance() or self.client.QtWidgets.QApplication([])
        modules, fake_player, fake_audio = fake_qt_multimedia_backend()
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "valid.mp4")
            Path(path).write_bytes(b"video-placeholder")
            with mock.patch.dict(sys.modules, modules), \
                    mock.patch.object(
                        self.client, "validate_video_file", return_value={"ok": True, "code": "ok"}
                    ):
                self.client._clear_comic_video_validation_cache()
                box = self.client.VideoPlayerBox(160, 90)
                self.assertTrue(box.set_media(path))
                player = fake_player.instances[-1]
                audio = fake_audio.instances[-1]
                box.release()
                app.processEvents()

        self.assertTrue(player.deleted)
        self.assertTrue(audio.deleted)
        self.assertIsNone(box.player)
        self.assertIsNone(box.audio)
        self.assertIsNone(box.item)
        self.assertIsNone(box.current_path)

    @unittest.skipUnless(qt_runtime_available(), "PySide6 runtime unavailable")
    def test_video_player_box_runtime_invalid_media_never_constructs_backend(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self.assertTrue(hasattr(self.client, "_clear_comic_video_validation_cache"))
        self.client.QtWidgets.QApplication.instance() or self.client.QtWidgets.QApplication([])
        modules, fake_player, _fake_audio = fake_qt_multimedia_backend()
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "invalid.mp4")
            Path(path).write_bytes(b"not-video")
            with mock.patch.dict(sys.modules, modules), \
                    mock.patch.object(
                        self.client, "validate_video_file",
                        return_value={"ok": False, "code": "media_missing_video_stream"},
                    ):
                self.client._clear_comic_video_validation_cache()
                before = len(fake_player.instances)
                box = self.client.VideoPlayerBox(160, 90)
                self.assertFalse(box.set_media(path))

        self.assertEqual(len(fake_player.instances), before)
        self.assertIsNone(box.player)

    @unittest.skipUnless(qt_runtime_available(), "PySide6 runtime unavailable")
    def test_comic_segment_video_cell_runtime_invalid_media_is_not_loaded(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        self.assertTrue(hasattr(self.client, "_clear_comic_video_validation_cache"))
        app = self.client.QtWidgets.QApplication.instance() or self.client.QtWidgets.QApplication([])
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "invalid.mp4")
            Path(path).write_bytes(b"not-video")
            segment = {"index": 3, "status": "done", "videoPath": path}
            self.client._clear_comic_video_validation_cache()
            with mock.patch.object(
                    self.client, "validate_video_file",
                    return_value={"ok": False, "code": "media_missing_video_stream"}), \
                    mock.patch.object(
                        self.client, "_replacement_error_id", return_value="err-cell-invalid"
                    ), \
                    mock.patch.object(self.client.VideoPlayerBox, "set_media") as set_media:
                cell = self.client.ComicSegmentVideoCell(segment)
                cell.show()
                app.processEvents()

        set_media.assert_not_called()
        self.assertIn("视频无效，请重试或查看日志", cell.video_box.hint.text())
        self.assertNotIn("错误编号", cell.video_box.hint.text())
        self.assertNotIn("err-cell-invalid", cell.video_box.hint.text())
        cell.close()

    def test_hybrid_plan_defaults_to_non_talking_even_when_transcript_exists(self):
        analysis = {
            "meta": {"duration": 12.0},
            "transcript": {
                "segments": [{"startSec": 1.0, "endSec": 5.0, "text": "今天介绍这款产品"}],
            },
        }

        plan = self.client._build_hybrid_replacement_plan(analysis, 12.0, segment_seconds=8)

        self.assertEqual(len(plan), 2)
        self.assertEqual(plan[0]["segmentType"], "non_talking")
        self.assertEqual(plan[0]["script"], "今天介绍这款产品")
        self.assertEqual(plan[1]["segmentType"], "non_talking")
        for segment in plan:
            self.assertEqual(segment["audioStatus"], "pending")
            self.assertEqual(segment["qcStatus"], "pending")
            self.assertIn("editedVideoPath", segment)
            self.assertIn("faceSwapPath", segment)

    def test_hybrid_plan_ignores_avatar_segments_env_for_replacement(self):
        analysis = {
            "meta": {"duration": 12.0},
            "transcript": {
                "segments": [{"startSec": 1.0, "endSec": 5.0, "text": "今天介绍这款产品"}],
            },
        }

        with mock.patch.dict(os.environ, {"VIDEO_REPLACE_ENABLE_AVATAR_SEGMENTS": "1"}):
            plan = self.client._build_hybrid_replacement_plan(analysis, 12.0, segment_seconds=8)

        self.assertEqual(plan[0]["segmentType"], "non_talking")
        self.assertEqual(plan[1]["segmentType"], "non_talking")

    def test_hybrid_plan_has_no_total_duration_limit_and_keeps_eight_second_segments(self):
        with mock.patch.dict(os.environ, {"VIDEO_REPLACE_MAX_DURATION_SEC": "60"}):
            plan = self.client._build_hybrid_replacement_plan({"meta": {"duration": 180}}, 180, segment_seconds=8)

        self.assertEqual(len(plan), 23)
        self.assertEqual(plan[0]["start"], 0.0)
        self.assertEqual(plan[0]["end"], 8.0)
        self.assertEqual(plan[-1]["start"], 176.0)
        self.assertEqual(plan[-1]["end"], 180.0)

    def test_hybrid_plan_merges_tail_shorter_than_remote_video_minimum(self):
        plan = self.client._build_hybrid_replacement_plan({"meta": {"duration": 17.47}}, 17.47, segment_seconds=8)

        self.assertEqual(len(plan), 2)
        self.assertEqual(plan[0]["start"], 0.0)
        self.assertEqual(plan[0]["end"], 8.0)
        self.assertEqual(plan[1]["start"], 8.0)
        self.assertEqual(plan[1]["end"], 17.47)
        self.assertGreaterEqual(plan[1]["duration"], 3.0)

    def test_hybrid_plan_keeps_scripted_segments_in_replacement_pipeline(self):
        analysis = {
            "meta": {"duration": 12.0},
            "transcript": {
                "segments": [{"startSec": 1.0, "endSec": 5.0, "text": "strict spoken script"}],
            },
        }

        plan = self.client._build_hybrid_replacement_plan(
            analysis, 12.0, segment_seconds=8, strict_script_audio=True)

        self.assertEqual(plan[0]["segmentType"], "non_talking")
        self.assertEqual(plan[0]["script"], "strict spoken script")
        self.assertEqual(plan[1]["segmentType"], "non_talking")

    def test_hybrid_pipeline_build_plan_preserves_source_entities_and_scripts(self):
        with tempfile.TemporaryDirectory() as td:
            analysis = {
                "meta": {"duration": 12.0},
                "transcript": {
                    "segments": [{"startSec": 1.0, "endSec": 5.0, "text": "strict spoken script"}],
                },
                "report": "人物：门店销售，产品：汽车，场景：展厅",
            }
            job = {
                "id": "job-plan",
                "outDir": td,
                "sourceVideoPath": str(Path(td) / "source.mp4"),
                "breakdownAnalysis": analysis,
                "productNotes": "uploaded product reference images: product.png",
                "modelNotes": "authorized model face",
                "audioMode": "tts",
                "strictScriptAudio": True,
                "noPersonMode": False,
                "pipeline": "hybrid_v2",
            }

            pipeline = self.pipeline_module.HybridReplacementPipeline(helpers=self.client)
            planned = pipeline.build_plan(job)

        self.assertEqual(planned["pipeline"], "hybrid_v2")
        self.assertEqual(planned["sourceReplacementEntities"], self.client._replacement_source_entities_from_analysis(analysis))
        self.assertEqual(planned["segments"][0]["script"], "strict spoken script")
        self.assertEqual(planned["segments"][0]["segmentType"], "talking")

    def test_hybrid_pipeline_execute_keeps_successful_fake_segments_done_and_passed(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "segment-01.mp4"
            saved = []
            progress_events = []
            job = {
                "id": "job-success",
                "outDir": td,
                "pipeline": "hybrid_v2",
                "sourceVideoPath": str(Path(td) / "source.mp4"),
                "segments": [{
                    "index": 1,
                    "start": 0.0,
                    "end": 8.0,
                    "duration": 8.0,
                    "status": "planned",
                    "audioStatus": "pending",
                    "qcStatus": "pending",
                    "script": "新的产品口播",
                    "prompt": "stable presenter",
                }],
            }
            pipeline = self.pipeline_module.HybridReplacementPipeline(helpers=self.client)

            def fake_save(value):
                saved.append(json.loads(json.dumps(value, ensure_ascii=False)))

            def fake_stage(job_value, segment, stage="", **_kwargs):
                return {
                    "stage": stage or str((segment or {}).get("status") or ""),
                    "stageLabel": stage or str((segment or {}).get("status") or ""),
                    "segmentElapsedSec": 0,
                    "segmentEtaSec": 0,
                }

            def fake_runner(_job, segment):
                output.write_bytes(b"segment")
                segment.update({
                    "status": "done",
                    "audioStatus": "passed",
                    "qcStatus": "passed",
                    "videoPath": str(output),
                    "providerTaskId": "task-seg-1",
                })
                return {"ok": True, "segment": segment, "path": str(output)}

            with mock.patch.object(self.client, "_save_replacement_job", side_effect=fake_save), \
                    mock.patch.object(self.client, "_replacement_timing_snapshot", side_effect=fake_stage), \
                    mock.patch.object(self.client, "_run_hybrid_replacement_segment", side_effect=fake_runner):
                result = pipeline.execute(
                    job,
                    selected_segments=job["segments"],
                    progress=lambda job_id, stage, message, segment_index, segments: progress_events.append({
                        "jobId": job_id,
                        "stage": stage,
                        "message": message,
                        "segmentIndex": segment_index,
                        "segments": segments,
                    }),
                )

        self.assertEqual(result["status"], "awaiting_review")
        self.assertEqual(result["segments"][0]["status"], "done")
        self.assertEqual(result["segments"][0]["qcStatus"], "passed")
        self.assertEqual(result["segments"][0]["providerTaskId"], "task-seg-1")
        self.assertTrue(any(event["stage"] == "awaiting_review" for event in progress_events))
        self.assertGreaterEqual(len(saved), 2)

    def test_hybrid_pipeline_public_payloads_hide_internal_segment_paths(self):
        with tempfile.TemporaryDirectory() as td:
            source_segment = Path(td) / "source-segment.mp4"
            source_segment_safe = Path(td) / "source-segment.subtitle-safe.mp4"
            segment_video = Path(td) / "segment-01.mp4"
            for path in (source_segment, source_segment_safe, segment_video):
                path.write_bytes(b"segment")
            job = {
                "id": "job-public",
                "outDir": td,
                "pipeline": "hybrid_v2",
                "sourceVideoPath": str(Path(td) / "source.mp4"),
                "segments": [{
                    "index": 1,
                    "start": 0.0,
                    "end": 8.0,
                    "duration": 8.0,
                    "status": "done",
                    "audioStatus": "passed",
                    "qcStatus": "passed",
                    "videoPath": str(segment_video),
                    "sourceSegmentPath": str(source_segment),
                    "sourceSegmentUploadPath": str(source_segment_safe),
                    "script": "稳定片段",
                }],
            }
            pipeline = self.pipeline_module.HybridReplacementPipeline(helpers=self.client)

            public_job = pipeline.public_job(job)
            public_segments = pipeline.public_segments(job)

        public_dump = json.dumps(public_job, ensure_ascii=False)
        segments_dump = json.dumps(public_segments, ensure_ascii=False)
        self.assertNotIn("sourceSegmentPath", public_dump)
        self.assertNotIn("sourceSegmentUploadPath", public_dump)
        self.assertNotIn(str(source_segment), public_dump)
        self.assertNotIn(str(source_segment_safe), public_dump)
        self.assertNotIn("sourceSegmentPath", segments_dump)
        self.assertNotIn("sourceSegmentUploadPath", segments_dump)
        self.assertNotIn(str(source_segment), segments_dump)
        self.assertNotIn(str(source_segment_safe), segments_dump)

    def test_hybrid_pipeline_execute_marks_partial_and_never_promotes_invalid_media_to_review(self):
        with tempfile.TemporaryDirectory() as td:
            saved = []
            job = {
                "id": "job-invalid",
                "outDir": td,
                "pipeline": "hybrid_v2",
                "sourceVideoPath": str(Path(td) / "source.mp4"),
                "segments": [
                    {
                        "index": 1,
                        "start": 0.0,
                        "end": 8.0,
                        "duration": 8.0,
                        "status": "planned",
                        "audioStatus": "pending",
                        "qcStatus": "pending",
                        "script": "第一段",
                    },
                    {
                        "index": 2,
                        "start": 8.0,
                        "end": 16.0,
                        "duration": 8.0,
                        "status": "planned",
                        "audioStatus": "pending",
                        "qcStatus": "pending",
                        "script": "第二段",
                    },
                ],
            }
            pipeline = self.pipeline_module.HybridReplacementPipeline(helpers=self.client)

            def fake_save(value):
                saved.append(json.loads(json.dumps(value, ensure_ascii=False)))

            def fake_stage(job_value, segment, stage="", **_kwargs):
                return {
                    "stage": stage or str((segment or {}).get("status") or ""),
                    "stageLabel": stage or str((segment or {}).get("status") or ""),
                    "segmentElapsedSec": 0,
                    "segmentEtaSec": 0,
                }

            def fake_runner(_job, segment):
                if segment["index"] == 1:
                    segment.update({
                        "status": "done",
                        "audioStatus": "passed",
                        "qcStatus": "passed",
                        "videoPath": str(Path(td) / "segment-01.mp4"),
                    })
                    Path(segment["videoPath"]).write_bytes(b"segment")
                    return {"ok": True, "segment": segment, "path": segment["videoPath"]}
                segment.update({
                    "status": "failed",
                    "audioStatus": "failed",
                    "qcStatus": "failed",
                    "error": "segment_invalid:download_html_body",
                    "errorId": "err-invalid-seg-2",
                })
                return {
                    "ok": False,
                    "segment": segment,
                    "error": segment["error"],
                    "errorId": segment["errorId"],
                }

            with mock.patch.object(self.client, "_save_replacement_job", side_effect=fake_save), \
                    mock.patch.object(self.client, "_replacement_timing_snapshot", side_effect=fake_stage), \
                    mock.patch.object(self.client, "_run_hybrid_replacement_segment", side_effect=fake_runner):
                result = pipeline.execute(job, selected_segments=job["segments"])

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["segments"][0]["status"], "done")
        self.assertEqual(result["segments"][1]["status"], "failed")
        self.assertNotEqual(result["status"], "awaiting_review")
        self.assertTrue(any(item["status"] == "partial" for item in saved))

    def test_hybrid_pipeline_execute_returns_canceled_job_after_segment_cancellation(self):
        with tempfile.TemporaryDirectory() as td:
            saved = []
            job = {
                "id": "job-cancel",
                "outDir": td,
                "pipeline": "hybrid_v2",
                "sourceVideoPath": str(Path(td) / "source.mp4"),
                "segments": [{
                    "index": 1,
                    "start": 0.0,
                    "end": 8.0,
                    "duration": 8.0,
                    "status": "planned",
                    "audioStatus": "pending",
                    "qcStatus": "pending",
                    "script": "取消段",
                }],
            }
            pipeline = self.pipeline_module.HybridReplacementPipeline(helpers=self.client)

            def fake_save(value):
                saved.append(json.loads(json.dumps(value, ensure_ascii=False)))

            def fake_stage(job_value, segment, stage="", **_kwargs):
                return {
                    "stage": stage or str((segment or {}).get("status") or ""),
                    "stageLabel": stage or str((segment or {}).get("status") or ""),
                    "segmentElapsedSec": 0,
                    "segmentEtaSec": 0,
                }

            def fake_runner(_job, _segment):
                raise RuntimeError("lk888_task_cancelled")

            with mock.patch.object(self.client, "_save_replacement_job", side_effect=fake_save), \
                    mock.patch.object(self.client, "_replacement_timing_snapshot", side_effect=fake_stage), \
                    mock.patch.object(self.client, "_run_hybrid_replacement_segment", side_effect=fake_runner):
                result = pipeline.execute(job, selected_segments=job["segments"])

        self.assertEqual(result["status"], "canceled")
        self.assertEqual(result["segments"][0]["status"], "cancel_requested")
        self.assertTrue(any(item["status"] == "canceled" for item in saved))

    def test_cancel_completion_event_uses_public_job_without_internal_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            internal_paths = [
                str(root),
                str(root / "source.mp4"),
                str(root / "output.mp4"),
                str(root / "segment-01.mp4"),
                str(root / "source-segment-01.mp4"),
                str(root / "uploaded-source-segment-01.mp4"),
            ]
            job = {
                "id": "job-cancel-public-event",
                "status": "cancel_requested",
                "outDir": internal_paths[0],
                "sourceVideoPath": internal_paths[1],
                "outputPath": internal_paths[2],
                "segments": [{
                    "index": 1,
                    "status": "cancel_requested",
                    "videoPath": internal_paths[3],
                    "sourceSegmentPath": internal_paths[4],
                    "sourceSegmentUploadPath": internal_paths[5],
                    "diagnostics": {"detail": "canceled at " + internal_paths[4]},
                }],
            }
            saved = []
            emitted = []
            bridge = types.SimpleNamespace(payload=types.SimpleNamespace(
                emit=lambda tag, payload: emitted.append((tag, payload))
            ))

            with mock.patch.object(
                    self.client,
                    "_cleanup_replacement_sensitive_materials",
                    return_value={"ok": True, "deleted": [], "failed": []},
                ), mock.patch.object(
                    self.client,
                    "_cleanup_replacement_temporary_materials",
                    return_value={"ok": True, "deleted": [], "failed": []},
                ), mock.patch.object(
                    self.client,
                    "_save_replacement_job",
                    side_effect=lambda value: saved.append(json.loads(json.dumps(value, ensure_ascii=False))),
                ), mock.patch.object(self.client, "BRIDGE", bridge):
                result = self.client._mark_replacement_job_canceled(job)

        self.assertIs(result, job)
        self.assertEqual(result["status"], "canceled")
        self.assertEqual(saved[-1]["sourceVideoPath"], internal_paths[1])
        self.assertEqual(saved[-1]["segments"][0]["sourceSegmentPath"], internal_paths[4])
        self.assertEqual(emitted[-1][0], "video_replace_done")
        public_payload = json.dumps(emitted[-1][1], ensure_ascii=False)
        for private_key in (
                "outDir", "sourceVideoPath", "outputPath", "videoPath",
                "sourceSegmentPath", "sourceSegmentUploadPath",
            ):
            self.assertNotIn(private_key, public_payload)
        for internal_path in internal_paths:
            self.assertNotIn(internal_path, public_payload)

    def test_hybrid_pipeline_retry_only_replays_requested_failed_segment(self):
        with tempfile.TemporaryDirectory() as td:
            saved = []
            progress_events = []
            segment_one = {
                "index": 1,
                "start": 0.0,
                "end": 8.0,
                "duration": 8.0,
                "status": "done",
                "audioStatus": "passed",
                "qcStatus": "passed",
                "videoPath": str(Path(td) / "segment-01.mp4"),
                "script": "保留成功片段",
            }
            Path(segment_one["videoPath"]).write_bytes(b"ok")
            segment_two = {
                "index": 2,
                "start": 8.0,
                "end": 16.0,
                "duration": 8.0,
                "status": "failed",
                "audioStatus": "failed",
                "qcStatus": "failed",
                "error": "provider submit failed",
                "errorId": "err-seg-2",
                "script": "失败片段 A",
            }
            segment_three = {
                "index": 3,
                "start": 16.0,
                "end": 24.0,
                "duration": 8.0,
                "status": "failed",
                "audioStatus": "failed",
                "qcStatus": "failed",
                "error": "provider submit failed",
                "errorId": "err-seg-3",
                "script": "失败片段 B",
            }
            job = {
                "id": "job-retry",
                "outDir": td,
                "pipeline": "hybrid_v2",
                "sourceVideoPath": str(Path(td) / "source.mp4"),
                "segments": [segment_one, segment_two, segment_three],
            }
            pipeline = self.pipeline_module.HybridReplacementPipeline(helpers=self.client)

            def fake_save(value):
                saved.append(json.loads(json.dumps(value, ensure_ascii=False)))

            def fake_stage(job_value, segment, stage="", **_kwargs):
                return {
                    "stage": stage or str((segment or {}).get("status") or ""),
                    "stageLabel": stage or str((segment or {}).get("status") or ""),
                    "segmentElapsedSec": 0,
                    "segmentEtaSec": 0,
                }

            def fake_runner(_job, segment):
                if segment["index"] != 3:
                    raise AssertionError("retry should only rerun the requested failed segment")
                output = Path(td) / "segment-03-retry.mp4"
                output.write_bytes(b"retry")
                segment.update({
                    "status": "done",
                    "audioStatus": "passed",
                    "qcStatus": "passed",
                    "videoPath": str(output),
                    "providerTaskId": "task-seg-3-retry",
                })
                return {"ok": True, "segment": segment, "path": str(output)}

            with mock.patch.object(self.client, "_save_replacement_job", side_effect=fake_save), \
                    mock.patch.object(self.client, "_replacement_timing_snapshot", side_effect=fake_stage), \
                    mock.patch.object(self.client, "_run_hybrid_replacement_segment", side_effect=fake_runner):
                result = pipeline.retry(
                    job,
                    segment_indices=[3],
                    progress=lambda job_id, stage, message, segment_index, segments: progress_events.append({
                        "jobId": job_id,
                        "stage": stage,
                        "message": message,
                        "segmentIndex": segment_index,
                        "segments": segments,
                    }),
                )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["segments"][0]["status"], "done")
        self.assertEqual(result["segments"][1]["status"], "failed")
        self.assertEqual(result["segments"][2]["status"], "done")
        self.assertEqual(result["segments"][2]["qcStatus"], "passed")
        self.assertEqual(result["segments"][2]["providerTaskId"], "task-seg-3-retry")
        self.assertEqual(job["lastRetryPreparation"]["segments"], [{"index": 3, "demotedCodes": []}])
        self.assertTrue(any(event["segmentIndex"] == 3 for event in progress_events))

    def test_comic_pipeline_execute_reuses_existing_remote_video_without_resubmit(self):
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

        with tempfile.TemporaryDirectory() as td:
            downloads = []
            segment = {
                "index": 1,
                "status": "failed",
                "script": "test script",
                "comicStoryboardId": 201,
                "videoUrl": "/uploads/existing-video.mp4",
                "comicVideoResult": {"status": "completed"},
            }
            job = {
                "id": "job-comic-existing-video-pipeline",
                "replacementMode": "comic_project",
                "comicProjectId": 88,
                "sourceVideoPath": str(Path(td) / "source.mp4"),
                "outDir": td,
                "comicAssets": {},
                "segments": [segment],
            }
            pipeline = self.pipeline_module.ComicProjectReplacementPipeline(helpers=self.client)

            with mock.patch.object(self.client, "ComicProjectAdapter", ExistingVideoComicAdapter), \
                    mock.patch.object(self.client, "_comic_base_url", return_value="https://manju.yunlingai.net"), \
                    mock.patch.object(self.client, "_save_replacement_job", lambda _value: None), \
                    mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                    mock.patch.object(self.client, "_replacement_timing_snapshot", return_value={
                        "stage": "comic_download_video",
                        "stageLabel": "comic_download_video",
                        "segmentElapsedSec": 0,
                        "segmentEtaSec": 0,
                    }):
                result = pipeline.execute(job, selected_segments=job["segments"])

        self.assertEqual(result["status"], "awaiting_review")
        self.assertEqual(segment["status"], "done")
        self.assertEqual(segment["startFrameUrl"], "https://manju.yunlingai.net/uploads/existing-start.png")
        self.assertEqual(segment["endFrameUrl"], "https://manju.yunlingai.net/uploads/existing-end.png")
        self.assertEqual(segment["videoUrl"], "https://manju.yunlingai.net/uploads/existing-video.mp4")
        self.assertEqual(downloads, [
            "https://manju.yunlingai.net/uploads/existing-start.png",
            "https://manju.yunlingai.net/uploads/existing-end.png",
            "https://manju.yunlingai.net/uploads/existing-video.mp4",
        ])

    def test_comic_pipeline_execute_recovers_image_submit_timeout_without_duplicate_submit(self):
        class RecoveringFrameComicAdapter:
            submit_image_calls = 0
            waited = []

            def get_project(self, project_id):
                return {"data": {"id": project_id, "storyboards": [{
                    "id": 201,
                    "sequence": 1,
                    "startFrameTaskId": "start-task",
                    "endFrameTaskId": "end-task",
                }]}}

            def upsert_manual_assets(self, *_args, **_kwargs):
                return {}

            def update_storyboard(self, *_args, **_kwargs):
                return {"ok": True}

            def submit_storyboard_image(self, *_args, **_kwargs):
                self.__class__.submit_image_calls += 1
                raise RuntimeError(
                    "HTTPConnectionPool(host='127.0.0.1', port=7897): Read timed out. (read timeout=120)"
                )

            def submit_storyboard_video(self, *_args, **_kwargs):
                return {"data": {"task_id": "video-task"}}

            def wait_task_result(self, task_id, **_kwargs):
                self.__class__.waited.append(task_id)
                if task_id == "start-task":
                    return "/uploads/start.png", {
                        "data": {"status": "completed", "task_id": "start-task", "cost": 0.031, "actual_model": "gpt-image-2"}
                    }
                if task_id == "end-task":
                    return "/uploads/end.png", {
                        "data": {"status": "completed", "task_id": "end-task", "cost": 0.032, "actual_model": "gpt-image-2"}
                    }
                return "/uploads/video.mp4", {
                    "data": {
                        "status": "completed",
                        "task_id": "video-task",
                        "requested_model": "seedance-requested",
                        "actual_model": "kling-fallback",
                        "fallback_model": "kling-fallback",
                        "fallback_reason": "provider-rejected",
                        "fallback_applied": True,
                        "cost": 0.42,
                    }
                }

            def download_media(self, _url, path, **_kwargs):
                Path(path).write_bytes(b"video")
                return path

        with tempfile.TemporaryDirectory() as td:
            segment = {
                "index": 1,
                "status": "pending",
                "script": "test script",
                "comicStoryboardId": 201,
            }
            job = {
                "id": "job-comic-frame-recovery-pipeline",
                "replacementMode": "comic_project",
                "comicProjectId": 88,
                "comicVideoModel": "seedance-requested",
                "model": "seedance-requested",
                "sourceVideoPath": str(Path(td) / "source.mp4"),
                "outDir": td,
                "comicAssets": {},
                "segments": [segment],
            }
            charges = []
            pipeline = self.pipeline_module.ComicProjectReplacementPipeline(helpers=self.client)

            def fake_charge(amount, **kwargs):
                charges.append((amount, dict(kwargs)))
                return True, 88.0, None

            with mock.patch.object(self.client, "ComicProjectAdapter", RecoveringFrameComicAdapter), \
                    mock.patch.object(self.client, "_comic_base_url", return_value="https://manju.yunlingai.net"), \
                    mock.patch.object(self.client, "charge", side_effect=fake_charge), \
                    mock.patch.object(self.client, "_comic_download_frame_image", return_value="frame.local"), \
                    mock.patch.object(self.client, "_prepare_comic_colored_pencil_references", lambda _job, _segment: _segment), \
                    mock.patch.object(self.client, "_save_replacement_job", lambda _value: None), \
                    mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                    mock.patch.object(self.client, "_replacement_timing_snapshot", return_value={
                        "stage": "comic_generate_flowchart",
                        "stageLabel": "comic_generate_flowchart",
                        "segmentElapsedSec": 0,
                        "segmentEtaSec": 0,
                    }):
                result = pipeline.execute(job, selected_segments=job["segments"])

        self.assertEqual(result["status"], "awaiting_review")
        self.assertEqual(RecoveringFrameComicAdapter.submit_image_calls, 1)
        self.assertEqual(
            RecoveringFrameComicAdapter.waited,
            ["start-task", "end-task", "video-task"],
        )
        self.assertEqual(segment["status"], "done")
        self.assertEqual(segment["comicRecoveryStatus"], "recovered")
        self.assertEqual(segment["requestedModel"], "seedance-requested")
        self.assertEqual(segment["actualModel"], "kling-fallback")
        self.assertEqual(segment["modelFallbackReason"], "provider-rejected")
        self.assertTrue(segment["modelFallbackApplied"])
        self.assertEqual([call[0] for call in charges], [0.031, 0.032, 0.42])

    def test_service_pipeline_defaults_missing_mode_to_product_default_and_routes_comic(self):
        client = self.client
        comic, hybrid = mock.Mock(), mock.Mock()
        with mock.patch.object(client, "_replacement_comic_pipeline", return_value=comic), \
                mock.patch.object(client, "_replacement_hybrid_pipeline", return_value=hybrid), \
                mock.patch.dict(os.environ, {"VIDEO_REPLACE_DEFAULT_MODE": "comic_project"}, clear=False):
            router = client._replacement_service_pipeline()
            job = {"id": "rvw_a", "segments": []}
            router.build_plan(job)
        self.assertEqual(job["replacementMode"], "comic_project")
        comic.build_plan.assert_called_once_with(job)
        hybrid.build_plan.assert_not_called()

    def test_service_pipeline_default_legacy_routes_to_hybrid(self):
        client = self.client
        comic, hybrid = mock.Mock(), mock.Mock()
        with mock.patch.object(client, "_replacement_comic_pipeline", return_value=comic), \
                mock.patch.object(client, "_replacement_hybrid_pipeline", return_value=hybrid), \
                mock.patch.dict(os.environ, {"VIDEO_REPLACE_DEFAULT_MODE": "legacy"}, clear=False):
            router = client._replacement_service_pipeline()
            job = {"id": "rvw_b"}
            router.build_plan(job)
        self.assertEqual(job["replacementMode"], "legacy")
        hybrid.build_plan.assert_called_once_with(job)
        comic.build_plan.assert_not_called()

    def test_service_pipeline_preserves_explicit_mode_and_routes_execute_to_comic(self):
        client = self.client
        comic, hybrid = mock.Mock(), mock.Mock()
        with mock.patch.object(client, "_replacement_comic_pipeline", return_value=comic), \
                mock.patch.object(client, "_replacement_hybrid_pipeline", return_value=hybrid), \
                mock.patch.dict(os.environ, {"VIDEO_REPLACE_DEFAULT_MODE": "legacy"}, clear=False):
            router = client._replacement_service_pipeline()
            job = {"id": "rvw_c", "replacementMode": "comic_project"}
            router.execute(job, selected_segments=[{"index": 1}], progress=None)
        # explicit comic mode wins over the legacy default, and is not rewritten
        comic.execute.assert_called_once()
        hybrid.execute.assert_not_called()
        self.assertEqual(job["replacementMode"], "comic_project")

    def test_build_video_service_uses_job_routing_pipeline(self):
        import tempfile
        import replacement_web
        with tempfile.TemporaryDirectory() as td:
            svc = replacement_web.build_video_service(td)
        self.assertEqual(type(svc.pipeline).__name__, "_ReplacementServicePipeline")

    def test_settle_actual_cost_is_idempotent_and_ignores_submit_estimate(self):
        charge_calls = []
        helper = types.SimpleNamespace(
            charge=lambda amount, **kwargs: charge_calls.append((amount, dict(kwargs))) or (True, 88.0, None),
            json_log=lambda *_args, **_kwargs: None,
            _CLIENT_JSON_LOGGER=object(),
            COMIC_VIDEO_GENERATION_CAP="comic_video_generation",
            COMIC_KEYFRAME_IMAGE_CAP="comic_keyframe_image",
        )
        job = {"id": "job-billing", "comicProjectId": 88, "_pipelineHelpers": helper}
        segment = {"index": 1}
        payload = {
            "task_id": "provider-1",
            "cost": 0.42,
            "estimated_cost": 9.99,
            "actual_model": "vidu/viduq3-mix_reference2video",
        }

        first = self.pipeline_module.settle_actual_cost(job, segment, payload, "video", "provider-1")
        second = self.pipeline_module.settle_actual_cost(job, segment, payload, "video", "provider-1")

        self.assertEqual(first["ref"], second["ref"])
        self.assertEqual(first["actualAmount"], 0.42)
        self.assertEqual(second["actualAmount"], 0.42)
        self.assertEqual(len(charge_calls), 1)
        self.assertEqual(charge_calls[0][0], 0.42)
        self.assertEqual(charge_calls[0][1]["capability"], "comic_video_generation")
        self.assertNotIn("estimated_cost", charge_calls[0][1]["meta"])

    def test_settle_actual_cost_returns_awaiting_actual_cost_and_keeps_refs_distinct(self):
        charge_calls = []
        helper = types.SimpleNamespace(
            charge=lambda amount, **kwargs: charge_calls.append((amount, dict(kwargs))) or (True, 88.0, None),
            json_log=lambda *_args, **_kwargs: None,
            _CLIENT_JSON_LOGGER=object(),
            COMIC_VIDEO_GENERATION_CAP="comic_video_generation",
            COMIC_KEYFRAME_IMAGE_CAP="comic_keyframe_image",
        )
        job = {"id": "job-awaiting", "comicProjectId": 301, "_pipelineHelpers": helper}
        segment = {"index": 2}

        awaiting = self.pipeline_module.settle_actual_cost(
            job,
            segment,
            {"task_id": "video-task", "estimated_cost": 12.34, "actual_model": "viduq3-cankaosheng"},
            "video",
            "video-task",
        )
        start = self.pipeline_module.settle_actual_cost(
            job,
            segment,
            {"task_id": "frame-start", "cost": 0.11, "actual_model": "gpt-image-2"},
            "keyframe",
            "frame-start",
            frame_index=1,
        )
        end = self.pipeline_module.settle_actual_cost(
            job,
            segment,
            {"task_id": "frame-end", "cost": 0.12, "actual_model": "gpt-image-2"},
            "keyframe",
            "frame-end",
            frame_index=2,
        )

        self.assertEqual(awaiting["status"], "awaiting_actual_cost")
        self.assertEqual(awaiting["taskId"], "video-task")
        self.assertIn(":frame:1:actual", start["ref"])
        self.assertIn(":frame:2:actual", end["ref"])
        self.assertNotEqual(start["ref"], end["ref"])
        self.assertNotEqual(start["ref"], awaiting.get("ref", ""))
        self.assertEqual([call[0] for call in charge_calls], [0.11, 0.12])

    def test_talking_segment_reuses_existing_tts_and_kling_digital_human(self):
        segment = {"index": 1, "segmentType": "talking", "script": "新的产品口播", "keyframeUrl": "https://x/key.png"}
        job = {"voiceId": "Zephyr", "digitalHumanMode": "std", "sceneImageUrl": "https://x/scene.png"}
        with mock.patch.object(self.client, "lk888_tts_voice", return_value="https://x/voice.mp3") as tts, \
                mock.patch.object(self.client, "lk888_digital_human", return_value="https://x/talking.mp4") as human:
            url = self.client._run_hybrid_talking_segment(job, segment)

        self.assertEqual(url, "https://x/talking.mp4")
        self.assertEqual(segment["ttsUrl"], "https://x/voice.mp3")
        tts.assert_called_once()
        self.assertEqual(tts.call_args[0], ("新的产品口播", "Zephyr"))
        self.assertTrue(callable(tts.call_args[1].get("cancel_check")))
        human.assert_called_once_with(
            "https://x/key.png",
            "https://x/voice.mp3",
            prompt=segment["prompt"],
            mode="std",
            scene_url="https://x/scene.png",
            cancel_check=mock.ANY,
        )
        self.assertTrue(callable(human.call_args[1].get("cancel_check")))

    def test_remote_media_url_rejects_loopback_and_private_hosts(self):
        self.assertTrue(self.client._is_remote_fetchable_media_url("https://cdn.example.com/a.png"))
        for url in (
            "http://127.0.0.1:9080/api/library/file/a.png",
            "http://localhost:9080/a.png",
            "http://192.168.1.20/a.png",
            "http://10.0.0.5/a.png",
            "data:image/png;base64,AAAA",
            "/tmp/a.png",
        ):
            with self.subTest(url=url):
                self.assertFalse(self.client._is_remote_fetchable_media_url(url))

    def test_keyframe_references_convert_local_sources_to_data_urls(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.jpg"
            product = root / "product.png"
            face = root / "face.png"
            scene = root / "scene.png"
            for path in (source, product, face, scene):
                path.write_bytes(b"test-image-bytes")
            job = {
                "productSourcePaths": [str(product)],
                "faceSourcePaths": [str(face)],
                "sceneImagePath": str(scene),
                "productImageUrls": ["http://127.0.0.1:9080/product.png"],
                "modelFaceUrl": "http://127.0.0.1:9080/face.png",
                "sceneImageUrl": "http://127.0.0.1:9080/scene.png",
            }

            refs = self.client._build_replacement_keyframe_references(
                job, {}, str(source), "http://127.0.0.1:9080/previous.png"
            )

        self.assertEqual(len(refs), 4)
        self.assertTrue(all(ref.startswith("data:image/") for ref in refs))
        self.assertFalse(any("127.0.0.1" in ref for ref in refs))

    def test_keyframe_references_migrate_existing_central_library_urls_in_memory(self):
        # The download-and-inline migration only applies to loopback central-library
        # URLs (a public central serves remotely-fetchable URLs that pass straight
        # through). Pin CENTRAL to loopback so this branch is exercised regardless of
        # the shipped default central host (public vs loopback).
        base = "http://127.0.0.1:9080"
        job = {
            "productImageUrls": [
                base + "/api/library/file/product/product.png"
            ],
            "modelFaceUrl": base + "/api/library/file/face/face.png",
            "sceneImageUrl": base + "/api/library/file/scene/scene.png",
        }
        response = mock.Mock(
            status_code=200,
            content=b"existing-library-image",
            headers={"Content-Type": "image/png"},
        )
        with mock.patch.object(self.client, "CENTRAL", base), \
                mock.patch.object(self.client.requests, "get", return_value=response) as get:
            refs = self.client._build_replacement_keyframe_references(job, {}, "", "")

        self.assertEqual(len(refs), 3)
        self.assertTrue(all(ref.startswith("data:image/png;base64,") for ref in refs))
        self.assertEqual(get.call_count, 3)

    def test_keyframe_references_reject_oversized_local_image(self):
        with tempfile.TemporaryDirectory() as td:
            product = Path(td) / "product.png"
            product.write_bytes(b"x" * 2048)
            with mock.patch.dict(os.environ, {"VIDEO_REPLACE_REFERENCE_MAX_BYTES": "1024"}):
                with self.assertRaisesRegex(RuntimeError, "video_replace_reference_invalid_size"):
                    self.client._build_replacement_keyframe_references(
                        {"productSourcePaths": [str(product)]}, {}, "", ""
                    )

    def test_image_result_preserves_public_upstream_url(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"data": {"task_id": "image-task-1"}, "accepted": True}
        with mock.patch.object(self.client, "lk888_config", return_value={
                "base_url": "https://proxy.example.com", "api_key": "test-key"
        }), mock.patch.object(self.client.requests, "post", return_value=response), \
                mock.patch.object(self.client.requests, "get") as download:
            result = self.client.lk888_image_result(
                "prompt", image_urls=["data:image/png;base64,AAAA"]
            )

        self.assertEqual({"data": {"task_id": "image-task-1"}, "accepted": True}, result)
        download.assert_not_called()

    def test_lk888_media_task_exits_polling_when_cancel_requested(self):
        post_response = mock.Mock(ok=True, status_code=200, text="")
        post_response.json.return_value = {"data": {"task_id": "task-1"}}
        poll_response = mock.Mock(status_code=200)
        poll_response.json.return_value = {"data": {"status": "running"}}
        checks = []

        def cancel_check():
            checks.append(True)
            return True

        with mock.patch.object(self.client, "lk888_config", return_value={
                "base_url": "https://proxy.example.com", "api_key": "test-key"
        }), mock.patch.object(self.client.requests, "post", return_value=post_response), \
                mock.patch.object(self.client.requests, "get", return_value=poll_response), \
                mock.patch.object(self.client.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "lk888_task_cancelled"):
                self.client.lk888_media_task(
                    "happyhorse-video-edit", {"prompt": "x"}, ["mp4"], tries=3, cancel_check=cancel_check
                )

        self.assertEqual(len(checks), 1)

    def test_keyframe_generation_retries_gateway_timeout_with_lighter_request(self):
        with tempfile.TemporaryDirectory() as td:
            segment = {"index": 1}
            job = {"outDir": td}
            refs = ["data:image/png;base64,source", "data:image/png;base64,product", "data:image/png;base64,face"]
            calls = []

            def image_result(prompt, size="1024x1024", model=None, image_urls=None):
                calls.append({"prompt": prompt, "size": size, "model": model, "image_urls": list(image_urls or [])})
                if len(calls) == 1:
                    raise RuntimeError("图片生成 504: <html><h1>504 Gateway Time-out</h1>")
                return b"png-bytes" * 10, "https://cdn.example.com/keyframe.png"

            with mock.patch.object(self.client, "_extract_replacement_source_frame", return_value=""), \
                    mock.patch.object(self.client, "_build_replacement_keyframe_references", return_value=refs), \
                    mock.patch.object(self.client, "_build_replacement_keyframe_prompt", return_value="prompt text"), \
                    mock.patch.object(self.client, "lk888_image_result", side_effect=image_result), \
                    mock.patch.object(self.client, "upload_asset_url", return_value=("https://cdn.example.com/library.png", {})):
                result = self.client._ensure_replacement_keyframe(job, segment)

        self.assertEqual(result, "https://cdn.example.com/keyframe.png")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["size"], "1024x1792")
        self.assertEqual(calls[0]["image_urls"], refs)
        self.assertEqual(calls[1]["size"], "1024x1024")
        self.assertEqual(calls[1]["image_urls"], refs[:2])
        self.assertEqual(segment["keyframeStatus"], "retry_ok")

    def test_upload_asset_url_prefers_public_https_proxy_url(self):
        response = {
            "ok": True,
            "id": "mat-1",
            "urls": ["/api/library/file/mat-1/product.png"],
            "publicUrls": ["https://temporary.trycloudflare.com/api/public-media/mat-1/product.png?token=signed"],
        }
        with mock.patch.object(self.client, "_external_image_upload_config", return_value=None), \
                mock.patch.object(self.client, "upload_materials", return_value=(200, response)):
            url, payload = self.client.upload_asset_url("/tmp/product.png", "product", "image")

        self.assertEqual(url, "https://temporary.trycloudflare.com/api/public-media/mat-1/product.png?token=signed")
        self.assertIs(payload, response)

    def test_upload_asset_url_uses_external_public_image_service_when_configured(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {
            "UPLOAD_API_URL": "https://img.yunlingai.net/api/upload",
            "UPLOAD_TOKEN": "secret-token",
            "PUBLIC_IMAGE_BASE_URL": "https://img.yunlingai.net/uploads",
        }, clear=False):
            image = Path(td) / "avatar.png"
            image.write_bytes(b"image-bytes")
            response = mock.Mock()
            response.status_code = 200
            response.json.return_value = {"filename": "avatar-public.png"}

            with mock.patch.object(self.client.requests, "post", return_value=response) as post, \
                    mock.patch.object(self.client, "upload_materials") as central_upload:
                url, payload = self.client.upload_asset_url(str(image), "avatar", "image")

        self.assertEqual(url, "https://img.yunlingai.net/uploads/avatar-public.png")
        self.assertEqual(payload["source"], "external_image_upload")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer secret-token")
        self.assertIn("file", post.call_args.kwargs["files"])
        central_upload.assert_not_called()

    def test_upload_asset_url_uses_external_public_upload_service_for_videos(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {
            "UPLOAD_API_URL": "https://img.yunlingai.net/api/upload",
            "UPLOAD_TOKEN": "secret-token",
            "PUBLIC_IMAGE_BASE_URL": "https://img.yunlingai.net/uploads",
        }, clear=False):
            video = Path(td) / "clip.mp4"
            video.write_bytes(b"video-bytes")
            response = mock.Mock()
            response.status_code = 200
            response.json.return_value = {"filename": "clip-public.mp4"}

            with mock.patch.object(self.client.requests, "post", return_value=response) as post, \
                    mock.patch.object(self.client, "upload_materials") as central_upload:
                url, payload = self.client.upload_asset_url(str(video), "clip", "video")

        self.assertEqual(url, "https://img.yunlingai.net/uploads/clip-public.mp4")
        self.assertEqual(payload["source"], "external_media_upload")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer secret-token")
        self.assertIn("file", post.call_args.kwargs["files"])
        central_upload.assert_not_called()

    def test_upload_asset_url_uses_external_public_upload_service_for_audio(self):
        with tempfile.TemporaryDirectory() as td:
            audio = Path(td) / "voice.mp3"
            audio.write_bytes(b"voice-bytes")
            response = mock.Mock()
            response.status_code = 200
            response.json.return_value = {"url": "https://img.yunlingai.net/uploads/voice-public.mp3"}
            with mock.patch.dict(os.environ, {
                "UPLOAD_API_URL": "https://img.yunlingai.net/api/upload",
                "UPLOAD_TOKEN": "secret-token",
                "PUBLIC_IMAGE_BASE_URL": "https://img.yunlingai.net/uploads",
            }, clear=False), \
                    mock.patch.object(self.client.requests, "post", return_value=response) as post, \
                    mock.patch.object(self.client, "upload_materials") as central_upload:
                url, payload = self.client.upload_asset_url(str(audio), "voice", "audio")

        self.assertEqual(url, "https://img.yunlingai.net/uploads/voice-public.mp3")
        self.assertEqual(payload["source"], "external_media_upload")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer secret-token")
        self.assertIn("file", post.call_args.kwargs["files"])
        central_upload.assert_not_called()

    def test_digital_human_scene_composition_sends_reference_images_in_compatible_fields(self):
        captured = {}
        def fake_image_result(_prompt, **kwargs):
            captured.update(kwargs)
            return b"png-bytes", "https://cdn.example.com/composed-avatar.png"

        with mock.patch.object(self.client, "_lk888_image_result_download", side_effect=fake_image_result):
            result = self.client._compose_digital_human_scene_avatar_url(
                "https://cdn.example.com/avatar.png",
                "https://cdn.example.com/showroom.png",
            )

        refs = ["https://cdn.example.com/avatar.png", "https://cdn.example.com/showroom.png"]
        self.assertEqual(result, "https://cdn.example.com/composed-avatar.png")
        self.assertEqual(captured.get("image_urls"), refs)
        self.assertEqual(captured.get("model"), "gpt-image-2")
        self.assertEqual(captured.get("size"), "1024x1536")

    def test_lk888_image_reference_url_fields_exclude_data_urls(self):
        captured = {}
        post_response = mock.Mock(status_code=200)
        post_response.json.return_value = {
            "data": [{"url": "https://cdn.example.com/generated.png"}]
        }
        refs = [
            "https://cdn.example.com/avatar.png",
            "data:image/png;base64,c2NlbmU=",
        ]

        def fake_post(_url, **kwargs):
            captured["json"] = kwargs.get("json")
            return post_response

        with mock.patch.object(self.client, "lk888_config", return_value={
                "base_url": "https://proxy.example.com", "api_key": "test-key"
        }), mock.patch.object(self.client.requests, "post", side_effect=fake_post), \
                mock.patch.object(self.client.requests, "get") as download:
            self.client.lk888_image_result("prompt", image_urls=refs)

        self.assertEqual(captured["json"].get("image_urls"), refs)
        self.assertEqual(captured["json"].get("images"), refs)
        self.assertEqual(captured["json"].get("reference_images"), refs)
        self.assertEqual(captured["json"].get("referenceImages"), refs)
        self.assertEqual((captured["json"].get("params") or {}).get("images"), refs)
        download.assert_not_called()

    def test_digital_human_sends_local_avatar_as_json_data_url(self):
        with tempfile.TemporaryDirectory() as td:
            avatar = Path(td) / "avatar.png"
            avatar.write_bytes(b"avatar-image")
            captured = {}

            def media_task(model, payload, exts, progress=None, tries=110):
                captured["model"] = model
                captured["payload"] = payload
                return "https://cdn.example.com/talking.mp4"

            with mock.patch.object(self.client, "lk888_media_task", side_effect=media_task), \
                    mock.patch.object(self.client, "lk888_media_task_multipart") as multipart_task:
                result = self.client.lk888_digital_human(
                    str(avatar),
                    "https://cdn.example.com/voice.wav",
                    prompt="中文口播",
                    scene_url="http://127.0.0.1:9080/scene.png",
                )

        self.assertEqual(result, "https://cdn.example.com/talking.mp4")
        self.assertEqual(captured["model"], "kling-avatar-image2video")
        self.assertIn("中文口播", captured["payload"]["prompt"])
        self.assertTrue(captured["payload"]["params"]["image"].startswith("data:image/png;base64,"))
        self.assertEqual(captured["payload"]["params"]["sound_file"], "https://cdn.example.com/voice.wav")
        self.assertNotIn("scene_image", captured["payload"]["params"])
        multipart_task.assert_not_called()

    def test_digital_human_prompt_forbids_model_generated_text(self):
        captured = {}

        def media_task(model, payload, exts, progress=None, tries=110, cancel_check=None):
            captured["payload"] = payload
            return "https://cdn.example.com/talking.mp4"

        with mock.patch.object(self.client, "_lk888_media_task_with_cancel", side_effect=media_task):
            self.client.lk888_digital_human(
                "https://cdn.example.com/avatar.png",
                "https://cdn.example.com/voice.wav",
                scene_url="https://cdn.example.com/scene.png",
            )

        self.assertIn("不要在画面中生成任何字幕", captured["payload"]["prompt"])
        self.assertIn("字幕由后期单独添加", captured["payload"]["prompt"])

    def test_generate_digital_human_burns_local_chinese_subtitles_after_download(self):
        emitted = []
        bridge = types.SimpleNamespace(payload=types.SimpleNamespace(
            emit=mock.Mock(side_effect=lambda tag, data: emitted.append((tag, data)))))
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "BRIDGE", bridge), \
                mock.patch.object(self.client, "run_bg", side_effect=lambda fn: fn()), \
                mock.patch.object(self.client, "try_charge", return_value=(True, "")), \
                mock.patch.object(self.client, "refund_cap") as refund, \
                mock.patch.object(self.client, "data_dir", return_value=td), \
                mock.patch.object(self.client, "lk888_tts_voice", return_value="https://cdn.example.com/voice.wav"), \
                mock.patch.object(self.client, "lk888_digital_human", return_value="https://cdn.example.com/talking.mp4"), \
                mock.patch.object(self.client, "_wf_download") as download, \
                mock.patch.object(self.client, "_burn_digital_human_subtitles",
                                  return_value={"ok": True, "mode": "burned",
                                                "videoPath": os.path.join(td, "digital_human_subtitled.mp4"),
                                                "subtitlePath": os.path.join(td, "digital_human.ass")}) as burn:
            def write_downloaded(_url, path):
                Path(path).write_bytes(b"raw-video" * 200)
            download.side_effect = write_downloaded

            self.client.generate_digital_human(
                "https://cdn.example.com/avatar.png",
                "local subtitle script",
                voice_id="Zephyr",
            )

        burn.assert_called_once()
        self.assertEqual(burn.call_args.args[1], "local subtitle script")
        self.assertTrue(any(data.get("stage") == "done" and
                            data.get("path", "").endswith("digital_human_subtitled.mp4")
                            for _tag, data in emitted))
        refund.assert_not_called()

    def test_digital_human_subtitle_ass_uses_script_text_and_video_duration(self):
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "digital_human.mp4"
            video.write_bytes(b"raw-video" * 200)
            with mock.patch.object(self.client, "_probe_video", return_value={"duration": 6.0}):
                result = self.client._write_digital_human_subtitle_ass(
                    str(video), "first sentence, second sentence, third sentence")

            self.assertTrue(result["ok"])
            self.assertGreaterEqual(len(result["events"]), 2)
            self.assertEqual(result["events"][0]["start"], 0.0)
            self.assertEqual(result["events"][-1]["end"], 6.0)
            self.assertTrue(Path(result["path"]).is_file())
            content = Path(result["path"]).read_text(encoding="utf-8-sig")
            self.assertIn("Dialogue:", content)
            self.assertIn("first sentence", content)
    def test_digital_human_scene_image_composes_background_before_tts(self):
        calls = []
        emitted = []
        bridge = types.SimpleNamespace(payload=types.SimpleNamespace(
            emit=mock.Mock(side_effect=lambda tag, data: emitted.append((tag, data)))))
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "BRIDGE", bridge), \
                mock.patch.object(self.client, "run_bg", side_effect=lambda fn: fn()), \
                mock.patch.object(self.client, "try_charge", return_value=(True, "")), \
                mock.patch.object(self.client, "refund_cap") as refund, \
                mock.patch.object(self.client, "data_dir", return_value=td), \
                mock.patch.object(self.client, "_compose_digital_human_scene_avatar_url",
                                  side_effect=lambda avatar, scene, scene_path=None: calls.append(("compose", avatar, scene, scene_path)) or "https://cdn.example.com/composed-avatar.png",
                                  create=True) as compose, \
                mock.patch.object(self.client, "_verify_digital_human_scene_background",
                                  side_effect=lambda scene, composed, scene_path=None: calls.append(("verify", scene, composed, scene_path)) or {
                                      "ok": True, "reason": "场景一致"
                                  }, create=True) as verify, \
                mock.patch.object(self.client, "lk888_tts_voice",
                                  side_effect=lambda script, voice_id: calls.append(("tts", script, voice_id)) or "https://cdn.example.com/voice.wav"), \
                mock.patch.object(self.client, "lk888_digital_human",
                                  side_effect=lambda avatar, sound, mode="std", scene_url=None, progress=None:
                                  calls.append(("digital", avatar, sound, scene_url)) or "https://cdn.example.com/talking.mp4"), \
                mock.patch.object(self.client, "_wf_download") as download:
            self.client.generate_digital_human(
                "https://cdn.example.com/avatar.png",
                "这是一段测试口播稿。",
                voice_id="Zephyr",
                scene_url="https://cdn.example.com/showroom.png",
            )

        compose.assert_called_once_with("https://cdn.example.com/avatar.png", "https://cdn.example.com/showroom.png", scene_path=None)
        verify.assert_called_once_with("https://cdn.example.com/showroom.png", "https://cdn.example.com/composed-avatar.png", scene_path=None)
        self.assertEqual(calls[0][0], "compose")
        self.assertEqual(calls[1][0], "verify")
        self.assertEqual(calls[2][0], "tts")
        self.assertEqual(calls[3], ("digital", "https://cdn.example.com/composed-avatar.png",
                                    "https://cdn.example.com/voice.wav", "https://cdn.example.com/showroom.png"))
        self.assertTrue(any("合成场景版人物图" in str(data.get("msg") or "") for _tag, data in emitted))
        download.assert_called_once()
        refund.assert_not_called()

    def test_digital_human_scene_mismatch_stops_before_tts(self):
        emitted = []
        bridge = types.SimpleNamespace(payload=types.SimpleNamespace(
            emit=mock.Mock(side_effect=lambda tag, data: emitted.append((tag, data)))))
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "BRIDGE", bridge), \
                mock.patch.object(self.client, "run_bg", side_effect=lambda fn: fn()), \
                mock.patch.object(self.client, "try_charge", return_value=(True, "")), \
                mock.patch.object(self.client, "refund_cap") as refund, \
                mock.patch.object(self.client, "data_dir", return_value=td), \
                mock.patch.object(self.client, "_compose_digital_human_scene_avatar_url",
                                  return_value="https://cdn.example.com/wrong-lake.png", create=True), \
                mock.patch.object(self.client, "_verify_digital_human_scene_background",
                                  return_value={"ok": False, "reason": "上传场景是汽车展厅，合成图是湖景"}, create=True), \
                mock.patch.object(self.client, "lk888_tts_voice") as tts, \
                mock.patch.object(self.client, "lk888_digital_human") as digital:
            self.client.generate_digital_human(
                "https://cdn.example.com/avatar.png",
                "这是一段测试口播稿。",
                voice_id="Zephyr",
                scene_url="https://cdn.example.com/showroom.png",
            )

        tts.assert_not_called()
        digital.assert_not_called()
        refund.assert_called_once()
        self.assertTrue(any("场景换背景失败" in str(data.get("msg") or "") and "湖景" in str(data.get("msg") or "")
                            for _tag, data in emitted))

    def test_digital_human_scene_mismatch_retries_with_strict_uploaded_scene(self):
        emitted = []
        compose_calls = []
        verify_calls = []
        bridge = types.SimpleNamespace(payload=types.SimpleNamespace(
            emit=mock.Mock(side_effect=lambda tag, data: emitted.append((tag, data)))))

        def compose(avatar, scene, scene_path=None, strict_scene=False):
            compose_calls.append((avatar, scene, scene_path, strict_scene))
            return ("https://cdn.example.com/wrong-park.png"
                    if len(compose_calls) == 1 else "https://cdn.example.com/showroom-avatar.png")

        def verify(scene, composed, scene_path=None):
            verify_calls.append((scene, composed, scene_path))
            return {"ok": len(verify_calls) == 2, "reason": "uploaded showroom vs generated outdoor park"}

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "BRIDGE", bridge), \
                mock.patch.object(self.client, "run_bg", side_effect=lambda fn: fn()), \
                mock.patch.object(self.client, "try_charge", return_value=(True, "")), \
                mock.patch.object(self.client, "refund_cap") as refund, \
                mock.patch.object(self.client, "data_dir", return_value=td), \
                mock.patch.object(self.client, "_compose_digital_human_scene_avatar_url", side_effect=compose), \
                mock.patch.object(self.client, "_verify_digital_human_scene_background", side_effect=verify), \
                mock.patch.object(self.client, "lk888_tts_voice", return_value="https://cdn.example.com/voice.wav") as tts, \
                mock.patch.object(self.client, "lk888_digital_human", return_value="https://cdn.example.com/talking.mp4") as digital, \
                mock.patch.object(self.client, "_wf_download"):
            self.client.generate_digital_human(
                "https://cdn.example.com/avatar.png",
                "test speech",
                voice_id="Zephyr",
                scene_url="https://cdn.example.com/showroom.png",
            )

        self.assertEqual(len(compose_calls), 2)
        self.assertFalse(compose_calls[0][3])
        self.assertTrue(compose_calls[1][3])
        self.assertEqual(len(verify_calls), 2)
        tts.assert_called_once()
        digital.assert_called_once()
        self.assertEqual(digital.call_args.args[0], "https://cdn.example.com/showroom-avatar.png")
        refund.assert_not_called()
        self.assertTrue(any(data.get("composed_avatar_url") == "https://cdn.example.com/wrong-park.png"
                            for _tag, data in emitted))

    def test_digital_human_scene_image_timeout_shows_actionable_message(self):
        emitted = []
        bridge = types.SimpleNamespace(payload=types.SimpleNamespace(
            emit=mock.Mock(side_effect=lambda tag, data: emitted.append((tag, data)))))
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "BRIDGE", bridge), \
                mock.patch.object(self.client, "run_bg", side_effect=lambda fn: fn()), \
                mock.patch.object(self.client, "try_charge", return_value=(True, "")), \
                mock.patch.object(self.client, "refund_cap") as refund, \
                mock.patch.object(self.client, "data_dir", return_value=td), \
                mock.patch.object(self.client, "_compose_digital_human_scene_avatar_url",
                                  side_effect=RuntimeError("digital_human_scene_avatar_image_timeout:lk888_proxy_error"),
                                  create=True), \
                mock.patch.object(self.client, "lk888_tts_voice") as tts, \
                mock.patch.object(self.client, "lk888_digital_human") as digital:
            self.client.generate_digital_human(
                "https://cdn.example.com/avatar.png",
                "这是一段测试口播稿。",
                voice_id="Zephyr",
                scene_url="https://cdn.example.com/showroom.png",
            )

        tts.assert_not_called()
        digital.assert_not_called()
        refund.assert_called_once()
        self.assertTrue(any("场景换背景图片生成超时" in str(data.get("msg") or "") and "稍后重试" in str(data.get("msg") or "")
                            for _tag, data in emitted))

    def test_digital_human_scene_policy_block_retries_with_safer_prompt(self):
        calls = []

        def image_result(prompt, size="1024x1024", model=None, image_urls=None):
            calls.append({"prompt": prompt, "size": size, "model": model, "image_urls": list(image_urls or [])})
            if len(calls) == 1:
                raise RuntimeError("图片生成 400: 您的提示已被内容安全策略阻止。请调整提示并再试一次。")
            return b"generated-image", "https://cdn.example.com/composed-avatar.png"

        with mock.patch.object(self.client, "lk888_image_result", side_effect=image_result):
            result = self.client._compose_digital_human_scene_avatar_url(
                "https://cdn.example.com/avatar.png",
                "https://cdn.example.com/showroom.png",
            )

        self.assertEqual(result, "https://cdn.example.com/composed-avatar.png")
        self.assertEqual([c["size"] for c in calls], ["1024x1536", "1024x1024"])
        self.assertIn("整体外观与穿着风格", calls[1]["prompt"])
        self.assertNotIn("脸部", calls[1]["prompt"])
        self.assertNotIn("人物身份", calls[1]["prompt"])
        self.assertEqual(calls[0]["image_urls"], calls[1]["image_urls"])

    def test_digital_human_scene_policy_block_shows_actionable_message(self):
        emitted = []
        bridge = types.SimpleNamespace(payload=types.SimpleNamespace(
            emit=mock.Mock(side_effect=lambda tag, data: emitted.append((tag, data)))))
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "BRIDGE", bridge), \
                mock.patch.object(self.client, "run_bg", side_effect=lambda fn: fn()), \
                mock.patch.object(self.client, "try_charge", return_value=(True, "")), \
                mock.patch.object(self.client, "refund_cap") as refund, \
                mock.patch.object(self.client, "data_dir", return_value=td), \
                mock.patch.object(self.client, "_compose_digital_human_scene_avatar_url",
                                  side_effect=RuntimeError("digital_human_scene_avatar_policy_blocked:内容安全策略阻止"),
                                  create=True), \
                mock.patch.object(self.client, "lk888_tts_voice") as tts, \
                mock.patch.object(self.client, "lk888_digital_human") as digital:
            self.client.generate_digital_human(
                "https://cdn.example.com/avatar.png",
                "这是一段测试口播稿。",
                voice_id="Zephyr",
                scene_url="https://cdn.example.com/showroom.png",
            )

        tts.assert_not_called()
        digital.assert_not_called()
        refund.assert_called_once()
        self.assertTrue(any("内容安全策略拦截" in str(data.get("msg") or "") and "换一张更中性的参考图" in str(data.get("msg") or "")
                            for _tag, data in emitted))

    def test_digital_human_scene_composition_uses_public_scene_url_for_lk888(self):
        with tempfile.TemporaryDirectory() as td:
            scene = Path(td) / "scene.png"
            scene.write_bytes(b"scene-image")
            captured = {}

            def image_result(prompt, size="1024x1024", model=None, image_urls=None):
                captured["prompt"] = prompt
                captured["size"] = size
                captured["image_urls"] = list(image_urls or [])
                return b"generated-image", "https://cdn.example.com/composed-avatar.png"

            with mock.patch.object(self.client, "lk888_image_result", side_effect=image_result):
                result = self.client._compose_digital_human_scene_avatar_url(
                    "https://cdn.example.com/avatar.png",
                    "https://cdn.example.com/showroom.png",
                    scene_path=str(scene),
                )

        self.assertEqual(result, "https://cdn.example.com/composed-avatar.png")
        self.assertEqual(captured["size"], "1024x1536")
        self.assertEqual(captured["image_urls"][0], "https://cdn.example.com/avatar.png")
        self.assertEqual(captured["image_urls"][1], "https://cdn.example.com/showroom.png")
        self.assertIn("第2张场景图", captured["prompt"])

    def test_digital_human_scene_composition_retries_proxy_timeout_with_square_size(self):
        with tempfile.TemporaryDirectory() as td:
            scene = Path(td) / "scene.png"
            scene.write_bytes(b"scene-image")
            calls = []

            def image_result(prompt, size="1024x1024", model=None, image_urls=None):
                calls.append({"prompt": prompt, "size": size, "model": model, "image_urls": list(image_urls or [])})
                if len(calls) == 1:
                    raise RuntimeError('图片生成 502: {"ok": false, "error": "lk888_proxy_error"}')
                return b"generated-image", "https://cdn.example.com/composed-avatar.png"

            with mock.patch.object(self.client, "lk888_image_result", side_effect=image_result):
                result = self.client._compose_digital_human_scene_avatar_url(
                    "https://cdn.example.com/avatar.png",
                    "https://cdn.example.com/showroom.png",
                    scene_path=str(scene),
                )

        self.assertEqual(result, "https://cdn.example.com/composed-avatar.png")
        self.assertEqual([c["size"] for c in calls], ["1024x1536", "1024x1024"])
        self.assertEqual(calls[0]["model"], "gpt-image-2")
        self.assertEqual(calls[1]["model"], "gpt-image-2")
        self.assertEqual(calls[0]["image_urls"], calls[1]["image_urls"])

    def test_digital_human_scene_trace_url_removes_signed_query(self):
        traced = self.client._digital_human_scene_trace_url(
            "https://cdn.example.com/generated/avatar.png?token=secret&expires=123")

        self.assertEqual(traced, "https://cdn.example.com/generated/avatar.png")

    def test_digital_human_scene_strict_retry_prompt_forbids_new_background(self):
        captured = {}

        def image_result(prompt, size="1024x1024", model=None, image_urls=None):
            captured["prompt"] = prompt
            return b"generated-image", "https://cdn.example.com/composed-avatar.png"

        with mock.patch.object(self.client, "lk888_image_result", side_effect=image_result):
            self.client._compose_digital_human_scene_avatar_url(
                "https://cdn.example.com/avatar.png",
                "https://cdn.example.com/showroom.png",
                strict_scene=True,
            )

        self.assertIn("唯一允许的背景来源", captured["prompt"])
        self.assertIn("不得生成户外公园", captured["prompt"])

    def test_digital_human_scene_background_verifier_rejects_mismatch(self):
        with mock.patch.object(self.client, "lk888_vision",
                               return_value='{"ok":false,"backgroundMatch":false,"reason":"上传场景是汽车展厅，合成图是湖景"}') as vision:
            result = self.client._verify_digital_human_scene_background(
                "https://cdn.example.com/showroom.png",
                "https://cdn.example.com/composed-avatar.png",
            )

        self.assertFalse(result["ok"])
        self.assertIn("湖景", result["reason"])
        vision.assert_called_once()

    def test_digital_human_without_scene_skips_background_composition(self):
        bridge = types.SimpleNamespace(payload=types.SimpleNamespace(emit=mock.Mock()))
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "BRIDGE", bridge), \
                mock.patch.object(self.client, "run_bg", side_effect=lambda fn: fn()), \
                mock.patch.object(self.client, "try_charge", return_value=(True, "")), \
                mock.patch.object(self.client, "data_dir", return_value=td), \
                mock.patch.object(self.client, "_compose_digital_human_scene_avatar_url", create=True) as compose, \
                mock.patch.object(self.client, "lk888_tts_voice", return_value="https://cdn.example.com/voice.wav"), \
                mock.patch.object(self.client, "lk888_digital_human", return_value="https://cdn.example.com/talking.mp4") as digital, \
                mock.patch.object(self.client, "_wf_download"):
            self.client.generate_digital_human(
                "https://cdn.example.com/avatar.png",
                "这是一段测试口播稿。",
                voice_id="Zephyr",
            )

        compose.assert_not_called()
        digital.assert_called_once()
        self.assertEqual(digital.call_args.args[0], "https://cdn.example.com/avatar.png")

    def test_digital_human_rejects_private_scene_before_tts(self):
        emitted = []
        bridge = types.SimpleNamespace(payload=types.SimpleNamespace(
            emit=mock.Mock(side_effect=lambda tag, data: emitted.append((tag, data)))))
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(self.client, "BRIDGE", bridge), \
                mock.patch.object(self.client, "run_bg", side_effect=lambda fn: fn()), \
                mock.patch.object(self.client, "try_charge", return_value=(True, "")), \
                mock.patch.object(self.client, "refund_cap") as refund, \
                mock.patch.object(self.client, "data_dir", return_value=td), \
                mock.patch.object(self.client, "lk888_tts_voice") as tts, \
                mock.patch.object(self.client, "lk888_digital_human") as digital:
            self.client.generate_digital_human(
                "https://cdn.example.com/avatar.png",
                "这是一段测试口播稿。",
                voice_id="Zephyr",
                scene_url="http://127.0.0.1:9080/showroom.png",
            )

        tts.assert_not_called()
        digital.assert_not_called()
        refund.assert_called_once()
        self.assertTrue(any("场景图不是远程模型可读取的公网图片" in str(data.get("msg") or "")
                            for _tag, data in emitted))

    def test_digital_human_scene_upload_copy_explains_forced_background(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn('QPushButton("上传场景图（强制换背景）")', src)
        self.assertIn("场景图可选；上传后会先强制合成背景", src)

    def test_digital_human_uploaded_assets_have_hover_delete_controls(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn("class HoverDeleteMediaFrame", src)
        self.assertIn("deleteRequested = QtCore.Signal(str)", src)
        self.assertIn("self.avatar_frame = HoverDeleteMediaFrame", src)
        self.assertIn("self.scene_frame = HoverDeleteMediaFrame", src)
        self.assertIn("self.sound_frame = HoverDeleteMediaFrame", src)
        self.assertIn("def _clear_uploaded_asset(self, kind):", src)
        self.assertIn("self.avatar_frame.set_preview_text(\"形象\\n预览\")", src)
        self.assertIn("self.scene_frame.set_preview_text(\"场景\\n可选\")", src)
        self.assertIn("self.sound_frame.set_preview_text(\"声音\\n可选\")", src)

    def test_digital_human_scene_error_and_status_identify_system_composed_image(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn("用户上传的场景图与系统合成的数字人图背景不一致", src)
        self.assertIn("系统中间合成图：", src)

    def test_talking_segment_rejects_loopback_avatar_before_tts(self):
        segment = {
            "index": 1,
            "script": "test speech",
            "keyframeUrl": "http://127.0.0.1:9080/keyframe.png",
        }
        with mock.patch.object(self.client, "lk888_tts_voice") as tts:
            with self.assertRaisesRegex(RuntimeError, "video_replace_avatar_not_remote_or_local"):
                self.client._run_hybrid_talking_segment({}, segment)
        tts.assert_not_called()

    def test_video_edit_request_preserves_source_video_and_references(self):
        job = {
            "productImageUrls": ["https://x/product.png"],
            "faceSourceUrls": ["https://x/face-left.png", "https://x/face-right.png"],
            "modelFaceUrl": "https://x/face-front.png",
            "sceneImageUrl": "https://x/scene.png",
            "scenePrompt": "bright modern bathroom",
            "resolution": "720p",
            "aspectRatio": "9:16",
        }
        segment = {"duration": 8, "prompt": "keep original body motion"}

        model, payload = self.client._build_hybrid_video_edit_request(job, segment, "https://x/source.mp4")

        self.assertEqual(model, "viduq3-turbo-cankaosheng")
        self.assertEqual(payload["source_video_url"], "https://x/source.mp4")
        self.assertEqual(payload["model_candidates"][:2], ["viduq3-turbo-cankaosheng", "wan2.7-cankaosheng"])
        self.assertEqual(payload["image_urls"], [
            "https://x/product.png",
            "https://x/face-front.png",
            "https://x/face-left.png",
            "https://x/face-right.png",
            "https://x/scene.png",
        ])
        self.assertEqual(payload["params"]["duration"], 8)
        self.assertEqual(payload["params"]["resolution"], "720p")
        self.assertIn("bright modern bathroom", payload["prompt"])

    def test_principal_video_edit_payload_uses_model_native_video_and_images_fields(self):
        model, payload = self.client._build_principal_video_edit_request(
            {
                "personReferenceUrls": ["https://cdn.example/person.jpg"],
                "productImageUrls": ["https://cdn.example/product.png"],
                "sceneImageUrl": "https://cdn.example/scene.png",
                "principalActor": {
                    "status": "detected",
                    "description": "the only presenter in the source video",
                },
                "resolution": "720p",
                "aspectRatio": "9:16",
            },
            {"duration": 8, "prompt": "replace the protagonist"},
            "https://cdn.example/source.mp4",
        )

        self.assertEqual(model, "happyhorse-video-edit")
        self.assertEqual(payload["video"], "https://cdn.example/source.mp4")
        self.assertEqual(payload["images"], [
            "https://cdn.example/person.jpg",
            "https://cdn.example/product.png",
            "https://cdn.example/scene.png",
        ])
        self.assertEqual(payload["resolution"], "720P")
        self.assertEqual(payload["audio_setting"], "origin")
        self.assertFalse(payload["watermark"])
        self.assertEqual(payload["video_url"], "https://cdn.example/source.mp4")
        self.assertEqual(payload["video_urls"], ["https://cdn.example/source.mp4"])
        self.assertEqual(payload["reference_video"], "https://cdn.example/source.mp4")
        self.assertEqual(payload["params"]["video"], "https://cdn.example/source.mp4")
        self.assertEqual(payload["params"]["images"], [
            "https://cdn.example/person.jpg",
            "https://cdn.example/product.png",
            "https://cdn.example/scene.png",
        ])
        self.assertEqual(payload["params"]["video_url"], "https://cdn.example/source.mp4")
        self.assertEqual(payload["image_urls"], [
            "https://cdn.example/person.jpg",
            "https://cdn.example/product.png",
            "https://cdn.example/scene.png",
        ])
        self.assertIn("只替换原视频中的一个主角", payload["prompt"])
        self.assertIn("保留原片主角的动作", payload["prompt"])
        self.assertIn("上传了产品图", payload["prompt"])
        self.assertIn("强制替换成上传产品", payload["prompt"])
        self.assertIn("上传了场景图", payload["prompt"])
        self.assertIn("强制替换成上传场景", payload["prompt"])

    def test_principal_video_edit_payload_keeps_lowercase_resolution_for_kwvideo_model(self):
        model, payload = self.client._build_principal_video_edit_request(
            {
                "model": "kwvideo-v2-quannengcankao",
                "personReferenceUrls": ["https://cdn.example/person.jpg"],
                "productImageUrls": ["https://cdn.example/product.png"],
                "sceneImageUrl": "https://cdn.example/scene.png",
                "principalActor": {
                    "status": "detected",
                    "description": "the only presenter in the source video",
                },
                "resolution": "720p",
                "aspectRatio": "9:16",
            },
            {"duration": 8, "prompt": "replace the protagonist"},
            "https://cdn.example/source.mp4",
        )

        self.assertEqual(model, "kwvideo-v2-quannengcankao")
        self.assertEqual(payload["resolution"], "720p")
        self.assertEqual(payload["params"]["resolution"], "720p")

    def test_principal_prompt_treats_subtitles_as_post_layer_not_source_text(self):
        _model, payload = self.client._build_principal_video_edit_request(
            {
                "personReferenceUrls": ["https://cdn.example/person.jpg"],
                "principalActor": {"status": "detected", "description": "main presenter"},
            },
            {"duration": 8, "prompt": "replace protagonist"},
            "https://cdn.example/source.mp4",
        )

        self.assertIn("字幕安全", payload["prompt"])
        self.assertIn("后期字幕层", payload["prompt"])
        self.assertNotIn("文字必须保持原视频一致", payload["prompt"])
        self.assertNotIn("屏幕文字保持原视频一致", payload["prompt"])

    def test_principal_prompt_uses_segment_script_for_tts_dialogue(self):
        _model, payload = self.client._build_principal_video_edit_request(
            {
                "audioMode": "tts",
                "personReferenceUrls": ["https://cdn.example/person.jpg"],
                "principalActor": {"status": "detected", "description": "main presenter"},
            },
            {
                "duration": 8,
                "prompt": "replace protagonist",
                "script": "凯美瑞7月最新政策我来报，现金优惠4万元。",
            },
            "https://cdn.example/source.mp4",
        )

        self.assertIn("口播稿", payload["prompt"])
        self.assertIn("凯美瑞7月最新政策我来报", payload["prompt"])
        self.assertIn("保留原片主角的动作、姿势、站位、镜头路径、构图和时长", payload["prompt"])
        self.assertNotIn("保留原片主角的动作、姿势、站位、镜头路径、构图、时长、原音和台词", payload["prompt"])

    def test_principal_prompt_uses_segment_script_for_uploaded_audio_dialogue(self):
        _model, payload = self.client._build_principal_video_edit_request(
            {
                "audioMode": "uploaded",
                "personReferenceUrls": ["https://cdn.example/person.jpg"],
                "principalActor": {"status": "detected", "description": "main presenter"},
            },
            {
                "duration": 8,
                "prompt": "replace protagonist",
                "script": "今天这台车的首付和月供我给你算清楚。",
            },
            "https://cdn.example/source.mp4",
        )

        self.assertIn("上传配音", payload["prompt"])
        self.assertIn("今天这台车的首付和月供我给你算清楚", payload["prompt"])
        self.assertNotIn("保留原片主角的动作、姿势、站位、镜头路径、构图、时长、原音和台词", payload["prompt"])

    def test_principal_prompt_uses_script_when_base_video_audio_is_source_for_lipsync(self):
        _model, payload = self.client._build_principal_video_edit_request(
            {
                "audioMode": "source",
                "promptAudioMode": "tts",
                "personReferenceUrls": ["https://cdn.example/person.jpg"],
                "principalActor": {"status": "detected", "description": "main presenter"},
            },
            {
                "duration": 8,
                "prompt": "replace protagonist",
                "script": "这段必须按新口播稿说出来。",
            },
            "https://cdn.example/source.mp4",
        )

        self.assertIn("这段必须按新口播稿说出来", payload["prompt"])
        self.assertIn("口播稿", payload["prompt"])
        self.assertNotIn("保留原片主角的动作、姿势、站位、镜头路径、构图、时长、原音和台词", payload["prompt"])

    def test_dialogue_timing_prompt_uses_centisecond_audio_schedule(self):
        timing = self.client._replacement_build_dialogue_timing(
            "凯美瑞优惠来了，现金优惠四万元。到店还可叠加厂补。",
            8.0,
        )
        prompt = self.client._replacement_dialogue_timing_prompt({
            "dialogueAudioDurationSec": 8.0,
            "dialogueTiming": timing,
        })

        self.assertGreaterEqual(len(timing), 3)
        self.assertEqual(timing[0]["startSec"], 0.0)
        self.assertEqual(timing[-1]["endSec"], 8.0)
        self.assertIn("本段最终口播音频时长：8.00 秒", prompt)
        self.assertIn("0.00-", prompt)
        self.assertIn("凯美瑞优惠来了", prompt)
        self.assertIn("严格按下列时间说话", prompt)

    def test_principal_prompt_frontloads_dialogue_timing_before_saved_prompt(self):
        long_saved_prompt = "源视频镜头节奏保持稳定。" * 8
        _model, payload = self.client._build_principal_video_edit_request(
            {
                "audioMode": "tts",
                "personReferenceUrls": ["https://cdn.example/person.jpg"],
                "principalActor": {"status": "detected", "description": "main presenter"},
            },
            {
                "duration": 8,
                "prompt": long_saved_prompt,
                "script": "前八秒必须按时间表说完这句新台词。",
                "dialogueAudioDurationSec": 8.0,
                "dialogueTiming": [{
                    "startSec": 0.0,
                    "endSec": 8.0,
                    "text": "前八秒必须按时间表说完这句新台词。",
                }],
            },
            "https://cdn.example/source.mp4",
        )

        self.assertIn("本段最终口播音频时长：8.00 秒", payload["prompt"])
        self.assertIn("0.00-8.00 秒：前八秒必须按时间表说完这句新台词。", payload["prompt"])
        self.assertLess(
            payload["prompt"].find("本段最终口播音频时长：8.00 秒"),
            payload["prompt"].find("源视频镜头节奏"),
        )
    def test_principal_prompt_keeps_script_before_long_saved_segment_prompt(self):
        long_saved_prompt = "旧拆解提示词只保留原片动作和台词。" * 160
        _model, payload = self.client._build_principal_video_edit_request(
            {
                "audioMode": "tts",
                "personReferenceUrls": ["https://cdn.example/person.jpg"],
                "principalActor": {"status": "detected", "description": "main presenter"},
            },
            {
                "duration": 8,
                "prompt": long_saved_prompt,
                "script": "前1800字内必须出现这句新台词。",
            },
            "https://cdn.example/source.mp4",
        )

        self.assertLess(payload["prompt"].find("前1800字内必须出现这句新台词"), 700)
        self.assertIn("前1800字内必须出现这句新台词", payload["prompt"])

    def test_principal_prompt_keeps_source_dialogue_when_audio_mode_is_source(self):
        _model, payload = self.client._build_principal_video_edit_request(
            {
                "audioMode": "source",
                "personReferenceUrls": ["https://cdn.example/person.jpg"],
                "principalActor": {"status": "detected", "description": "main presenter"},
            },
            {
                "duration": 8,
                "prompt": "replace protagonist",
                "script": "这段用户改稿不能覆盖原片声音模式。",
            },
            "https://cdn.example/source.mp4",
        )

        self.assertIn("保留原片主角的动作、姿势、站位、镜头路径、构图、时长、原音和台词", payload["prompt"])
        self.assertNotIn("这段用户改稿不能覆盖原片声音模式", payload["prompt"])

    def test_hybrid_video_edit_prompt_treats_subtitles_as_post_layer_not_source_text(self):
        _model, payload = self.client._build_hybrid_video_edit_request(
            {
                "productImageUrls": ["https://x/product.png"],
                "modelFaceUrl": "https://x/face-front.png",
            },
            {"duration": 8, "prompt": "preserve motion"},
            "https://x/source.mp4",
        )

        self.assertIn("字幕安全", payload["prompt"])
        self.assertIn("后期字幕层", payload["prompt"])
        self.assertIn("不要复刻", payload["prompt"])

    def test_video_edit_request_appends_action_frames_as_motion_only_references(self):
        job = {
            "actionControlEnabled": True,
            "productImageUrls": ["https://x/product.png"],
            "modelFaceUrl": "https://x/face-front.png",
            "sceneImageUrl": "https://x/scene.png",
        }
        segment = {
            "duration": 8,
            "prompt": "keep original body motion",
            "actionFrameUrls": ["https://x/action-01.jpg", "https://x/action-02.jpg"],
        }

        _model, payload = self.client._build_hybrid_video_edit_request(job, segment, "https://x/source.mp4")

        self.assertEqual(payload["image_urls"], [
            "https://x/product.png",
            "https://x/face-front.png",
            "https://x/scene.png",
            "https://x/action-01.jpg",
            "https://x/action-02.jpg",
        ])
        self.assertIn("原片动作关键帧只作为动作、姿态、站位、镜头和构图参考", payload["prompt"])
        self.assertIn("不要把原片动作关键帧中的人物脸当作身份参考", payload["prompt"])

    def test_video_edit_request_appends_previous_generated_frame_for_identity_continuity(self):
        job = {
            "productImageUrls": ["https://x/product.png"],
            "modelFaceUrl": "https://x/face-front.png",
        }
        segment = {
            "duration": 8,
            "prompt": "keep original body motion",
            "continuityFrameUrl": "https://x/previous-generated-last.jpg",
        }

        _model, payload = self.client._build_hybrid_video_edit_request(job, segment, "https://x/source.mp4")

        self.assertIn("https://x/previous-generated-last.jpg", payload["image_urls"])
        self.assertIn("上一段生成结果参考帧", payload["prompt"])
        self.assertIn("保持同一个新人设、脸部观感、发型和服装连续", payload["prompt"])

    def test_remote_video_payload_normalizes_happyhorse_resolution_without_changing_primary_payload(self):
        payload = {
            "prompt": "x",
            "source_video_url": "https://x/source.mp4",
            "image_urls": ["https://x/ref.png"],
            "params": {"duration": 8, "resolution": "720p", "aspect_ratio": "9:16"},
        }

        normalized = self.client._replacement_remote_video_payload_for_model(payload, "happyhorse-1.1-r2v")

        self.assertEqual(normalized["params"]["resolution"], "720P")
        self.assertEqual(payload["params"]["resolution"], "720p")
        self.assertNotIn("source_video_url", normalized)

    def test_replacement_model_candidates_preserve_custom_reference_model_first(self):
        job = {"model": "wan2.7-cankaosheng"}

        candidates = self.client._replacement_model_candidates(job)

        self.assertEqual(candidates[0], "wan2.7-cankaosheng")
        self.assertIn("viduq3-turbo-cankaosheng", candidates)
        self.assertNotIn("happyhorse-video-edit", candidates)

    def test_replacement_supported_model_rows_include_sd20_all_purpose_from_catalog(self):
        rows = [
            {"name": "happyhorse-video-edit", "display_name": "HappyHorse Video Edit", "type": "video"},
            {"name": "sd20-all-reference", "display_name": "SD 2.0 全能参考", "type": "video"},
            {"name": "sora-2", "display_name": "Sora 2", "type": "video"},
            {"name": "gpt-image-2", "display_name": "Image", "type": "image"},
        ]

        supported = self.client._replacement_supported_model_rows(rows)
        names = [row["name"] for row in supported]

        self.assertIn("happyhorse-video-edit", names)
        self.assertIn("sd20-all-reference", names)
        self.assertNotIn("sora-2", names)
        self.assertNotIn("gpt-image-2", names)

    def test_replacement_supported_model_rows_include_known_sd20_all_purpose_model(self):
        supported = self.client._replacement_supported_model_rows([])
        names = [row["name"] for row in supported]

        self.assertIn("kwvideo-v2-quannengcankao", names)
        row = next(row for row in supported if row["name"] == "kwvideo-v2-quannengcankao")
        self.assertEqual(row["display_name"], "SD 2.0 全能参考")
        self.assertEqual(row["type"], "video")

    def test_replacement_supported_model_rows_include_known_hailuo_h3_all_purpose_model(self):
        supported = self.client._replacement_supported_model_rows([])
        names = [row["name"] for row in supported]

        self.assertIn("hailuo-h3-quannengcankao", names)
        row = next(row for row in supported if row["name"] == "hailuo-h3-quannengcankao")
        self.assertEqual(row["display_name"], "海螺 H3 全能参考")
        self.assertEqual(row["type"], "video")

    def test_replacement_configured_model_allows_hailuo_h3_all_purpose_model(self):
        candidates = self.client._replacement_model_candidates({"model": "hailuo-h3-quannengcankao"})

        self.assertEqual(candidates[0], "hailuo-h3-quannengcankao")

    def test_hybrid_video_edit_puts_reference_images_into_params_for_lk888(self):
        # LK888 只读 params 里的字段,顶层 image_urls 被忽略。
        # 覆盖 image_url(单数,hailuo-h3/kwvideo-v2)、images(复数,viduq3)、
        # image_urls、reference_images 四种别名。
        job = {
            "productImageUrls": ["https://x/product.png"],
            "modelFaceUrl": "https://x/face-front.png",
            "sceneImageUrl": "https://x/scene.png",
        }
        _model, payload = self.client._build_hybrid_video_edit_request(
            job, {"duration": 8, "prompt": "keep motion"}, "https://x/source.mp4"
        )
        expected_refs = [
            "https://x/product.png",
            "https://x/face-front.png",
            "https://x/scene.png",
        ]
        self.assertEqual(payload["params"]["image_url"], expected_refs)
        self.assertEqual(payload["params"]["images"], expected_refs)
        self.assertEqual(payload["params"]["image_urls"], expected_refs)
        self.assertEqual(payload["params"]["reference_images"], expected_refs)
        self.assertEqual(payload["image_urls"], expected_refs)

    def test_hybrid_video_edit_omits_image_fields_when_no_refs(self):
        # refs 为空时不下发空数组,避免 LK888 触发"提供了但为空"的分支。
        job = {}
        _model, payload = self.client._build_hybrid_video_edit_request(
            job, {"duration": 8, "prompt": "text to video"}, "https://x/source.mp4"
        )
        self.assertNotIn("image_url", payload["params"])
        self.assertNotIn("images", payload["params"])
        self.assertNotIn("image_urls", payload["params"])
        self.assertNotIn("reference_images", payload["params"])

    def test_remote_video_payload_maps_hailuo_h3_resolution_720p_to_768P(self):
        payload = {
            "prompt": "x",
            "source_video_url": "https://x/source.mp4",
            "image_urls": ["https://x/ref.png"],
            "params": {
                "duration": 8,
                "resolution": "720p",
                "aspect_ratio": "9:16",
                "image_url": ["https://x/ref.png"],
            },
        }
        normalized = self.client._replacement_remote_video_payload_for_model(
            payload, "hailuo-h3-quannengcankao"
        )
        self.assertEqual(normalized["params"]["resolution"], "768P")
        self.assertEqual(normalized["params"]["image_url"], ["https://x/ref.png"])
        self.assertNotIn("source_video_url", normalized)

    def test_remote_video_payload_maps_hailuo_h3_resolution_1080p_to_2K(self):
        payload = {
            "params": {"duration": 6, "resolution": "1080p", "aspect_ratio": "16:9"},
        }
        normalized = self.client._replacement_remote_video_payload_for_model(
            payload, "hailuo-h3-quannengcankao"
        )
        self.assertEqual(normalized["params"]["resolution"], "2K")

    def test_remote_video_payload_preserves_hailuo_h3_native_resolutions(self):
        for input_res in ("768P", "768p", "2K", "2k"):
            payload = {"params": {"resolution": input_res}}
            normalized = self.client._replacement_remote_video_payload_for_model(
                payload, "hailuo-h3-quannengcankao"
            )
            self.assertIn(
                normalized["params"]["resolution"],
                ("768P", "2K"),
                msg="input=%s got=%s" % (input_res, normalized["params"]["resolution"]),
            )

    def test_agent_video_reference_limit_includes_hailuo_h3(self):
        # Agent 模式下 hailuo-h3 上限 9 张(LK888 spec)。
        limit = self.client._agent_video_reference_limit("hailuo-h3-quannengcankao")
        self.assertEqual(limit, 9)

    def test_principal_replacement_model_candidates_do_not_fallback_to_reference_video(self):
        candidates = self.client._replacement_model_candidates({
            "principalReplacementMode": "source_video_edit",
            "model": "happyhorse-video-edit",
        })

        self.assertEqual(candidates, ["happyhorse-video-edit"])

    def test_principal_replacement_model_candidates_use_selected_task_model(self):
        candidates = self.client._replacement_model_candidates({
            "principalReplacementMode": "source_video_edit",
            "model": "sd20-all-reference",
        })

        self.assertEqual(candidates, ["sd20-all-reference"])

    def test_principal_route_uses_selected_task_model(self):
        job = {
            "principalReplacementMode": "source_video_edit",
            "model": "sd20-all-reference",
            "personReferenceUrls": ["https://x/person.jpg"],
            "principalActor": {"status": "detected", "description": "main presenter"},
        }

        model, payload = self.client._build_hybrid_video_edit_request(
            job, {"duration": 8}, "https://x/source.mp4")

        self.assertEqual(model, "sd20-all-reference")
        self.assertEqual(payload["model_candidates"], ["sd20-all-reference"])
        self.assertEqual(payload["video"], "https://x/source.mp4")
        self.assertEqual(payload["images"], ["https://x/person.jpg"])

    def test_principal_replacement_is_disabled_by_explicit_rollback_flag(self):
        with mock.patch.dict(
                os.environ, {"VIDEO_REPLACE_PRINCIPAL_REPLACEMENT": "0"}, clear=False):
            self.assertFalse(self.client._principal_replacement_enabled({
                "principalReplacementMode": "source_video_edit",
            }))

    def test_principal_replacement_is_disabled_for_pure_product_jobs(self):
        self.assertFalse(self.client._principal_replacement_enabled({
            "principalReplacementMode": "source_video_edit",
            "noPersonMode": True,
        }))

    def test_principal_model_configuration_is_ignored_after_rollback(self):
        with mock.patch.dict(os.environ, {
            "VIDEO_REPLACE_PRINCIPAL_REPLACEMENT": "0",
            "VIDEO_REPLACE_PRINCIPAL_MODEL": "custom-principal-model",
        }, clear=False):
            candidates = self.client._replacement_model_candidates({
                "principalReplacementMode": "source_video_edit",
                "model": "custom-principal-model",
            })

        self.assertNotIn("custom-principal-model", candidates)
        self.assertIn("viduq3-turbo-cankaosheng", candidates)

    def test_principal_route_sends_source_video_to_happyhorse(self):
        job = {
            "principalReplacementMode": "source_video_edit",
            "personReferenceUrls": ["https://x/person.jpg"],
            "principalActor": {"status": "detected", "description": "main presenter"},
        }

        model, payload = self.client._build_hybrid_video_edit_request(
            job, {"duration": 8}, "https://x/source.mp4")

        self.assertEqual(model, "happyhorse-video-edit")
        self.assertEqual(payload["video"], "https://x/source.mp4")
        self.assertEqual(payload["images"], ["https://x/person.jpg"])
        self.assertEqual(payload["model_candidates"], ["happyhorse-video-edit"])

    def test_principal_request_requires_detected_or_manual_source_actor(self):
        with self.assertRaisesRegex(RuntimeError, "principal_source_actor_required"):
            self.client._build_principal_video_edit_request(
                {
                    "personReferenceUrls": ["https://x/person.jpg"],
                    "principalActor": {"status": "failed"},
                },
                {"duration": 8},
                "https://x/source.mp4",
            )

    def test_principal_route_preserves_source_video_fields_for_remote_request(self):
        payload = {
            "video": "https://x/source.mp4",
            "images": ["https://x/person.jpg"],
            "video_url": "https://x/source.mp4",
            "video_urls": ["https://x/source.mp4"],
            "reference_video": "https://x/source.mp4",
            "image_urls": ["https://x/person.jpg"],
            "model_candidates": ["happyhorse-video-edit"],
            "params": {"resolution": "720P"},
        }

        remote = self.client._replacement_remote_video_payload_for_model(
            payload, "happyhorse-video-edit")

        self.assertEqual(remote["video"], "https://x/source.mp4")
        self.assertEqual(remote["images"], ["https://x/person.jpg"])
        self.assertEqual(remote["video_url"], "https://x/source.mp4")
        self.assertEqual(remote["video_urls"], ["https://x/source.mp4"])
        self.assertEqual(remote["reference_video"], "https://x/source.mp4")
        self.assertNotIn("model_candidates", remote)

    def test_principal_actor_extractor_crops_the_vision_selected_frame(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as td:
            frames = []
            for index in range(6):
                path = Path(td) / ("frame_%02d.jpg" % (index + 1))
                Image.new("RGB", (100, 200), (20 + index, 40, 60)).save(path)
                frames.append({"time": index * 0.5, "path": str(path)})
            response = (
                '{"bestFrame":2,"bbox":{"x":100,"y":100,"width":300,"height":700},'
                '"confidence":0.92,"description":"唯一的展厅讲解主角",'
                '"evidence":"在六张源片帧中持续出现"}'
            )

            with mock.patch.object(self.client, "_extract_breakdown_frames", return_value=frames), \
                    mock.patch.object(self.client, "_image_data_url", side_effect=lambda path: "data:" + path), \
                    mock.patch.object(self.client, "lk888_vision", return_value=response) as vision:
                actor = self.client._extract_replacement_principal_actor(
                    "source.mp4", {}, td)

            self.assertEqual(actor["status"], "detected")
            self.assertEqual(actor["bestFrameIndex"], 2)
            self.assertEqual(actor["bbox"]["x"], 100)
            self.assertTrue(os.path.isfile(actor["previewPath"]))
            self.assertEqual(len(vision.call_args[0][1]), 6)

    def test_principal_actor_extractor_requires_structured_vision_response(self):
        with tempfile.TemporaryDirectory() as td:
            frame = Path(td) / "frame.jpg"
            frame.write_bytes(b"frame")
            frames = [{"time": 0.2, "path": str(frame)}]
            with mock.patch.object(self.client, "_extract_breakdown_frames", return_value=frames), \
                    mock.patch.object(self.client, "_image_data_url", return_value="data:image/jpeg;base64,aaa"), \
                    mock.patch.object(self.client, "lk888_vision", return_value="无法判断"):
                with self.assertRaisesRegex(RuntimeError, "principal_actor_extract_invalid_response"):
                    self.client._parse_principal_actor_response("无法判断", frames)

    def test_principal_actor_extractor_degrades_invalid_response_to_manual_candidates(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as td:
            frames = []
            for index in range(3):
                path = Path(td) / ("frame_%02d.jpg" % (index + 1))
                Image.new("RGB", (120, 180), (20 + index, 60, 90)).save(path)
                frames.append({"time": index * 0.5, "path": str(path)})

            with mock.patch.object(self.client, "_extract_breakdown_frames", return_value=frames), \
                    mock.patch.object(self.client, "_image_data_url", side_effect=lambda path: "data:" + path), \
                    mock.patch.object(self.client, "lk888_vision", return_value="无法判断"), \
                    mock.patch.object(self.client, "_replacement_error_id", return_value="err-invalid-actor"):
                actor = self.client._extract_replacement_principal_actor(
                    "source.mp4", {}, td)

            self.assertEqual(actor["status"], "manual_required")
            self.assertEqual(actor["error"], "principal_actor_extract_invalid_response")
            self.assertEqual(actor["errorId"], "err-invalid-actor")
            self.assertEqual(actor["previewPath"], str(Path(td) / "frame_01.jpg"))
            self.assertEqual(actor["candidatePaths"], [item["path"] for item in frames])
            self.assertIn("手动", actor["evidence"])

    def test_principal_actor_extractor_marks_low_confidence_for_manual_review(self):
        frames = [{"time": 0.2, "path": "frame.jpg"}]
        actor = self.client._parse_principal_actor_response(
            '{"bestFrame":1,"bbox":{"x":0,"y":0,"width":1000,"height":1000},'
            '"confidence":0.2,"description":"不确定"}', frames)

        self.assertEqual(actor["status"], "manual_required")
        self.assertEqual(actor["bestFrameIndex"], 1)

    def test_person_reference_validation_requires_a_full_body_image(self):
        with self.assertRaisesRegex(RuntimeError, "person_reference_full_body_required"):
            self.client._validate_person_reference_paths([])

    def test_principal_visual_qc_requires_replacement_and_other_subject_preservation(self):
        result = self.client._parse_principal_visual_qc(
            '{"principalReplacementMatch":false,"otherSubjectsPreserved":true,'
            '"motionPreserved":true}'
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "principal_replacement_mismatch")

    def test_principal_visual_qc_rejects_motion_drift(self):
        result = self.client._parse_principal_visual_qc(
            '{"principalReplacementMatch":true,"otherSubjectsPreserved":true,'
            '"motionPreserved":false,"fullBodyAppearanceMatch":true}'
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "principal_motion_mismatch")

    def test_principal_visual_qc_rejects_original_hair_or_clothes(self):
        result = self.client._parse_principal_visual_qc(
            '{"principalReplacementMatch":true,"otherSubjectsPreserved":true,'
            '"motionPreserved":true,"fullBodyAppearanceMatch":false,'
            '"reason":"仍保留原片主角发型和休闲装"}'
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "principal_appearance_mismatch")

    def test_principal_visual_qc_sends_person_references_and_blocks_mismatch(self):
        job = {
            "principalReplacementMode": "source_video_edit",
            "productImageUrls": ["https://x/product.png"],
            "personReferenceUrls": ["https://x/person-full.png"],
            "temporaryMaterialIds": [],
        }
        segment = {"index": 1}
        response = (
            '{"sourceProductVisible":true,"faceMatch":true,"productMatch":true,'
            '"logoTextReadable":true,"sceneMatch":true,"topicMatch":true,'
            '"roleMatch":true,"structureMatch":true,"severeDrift":false,'
            '"principalReplacementMatch":false,"otherSubjectsPreserved":true,'
            '"motionPreserved":true,"fullBodyAppearanceMatch":false,'
            '"reason":"仍是原人物"}'
        )
        captured = {}

        def vision(prompt, media, max_tokens=500):
            captured["prompt"] = prompt
            captured["media"] = list(media)
            return response

        with mock.patch.object(self.client, "upload_asset_url", return_value=(
                "https://x/result.mp4", {"data": {"id": "temp-video"}}
        )), mock.patch.object(self.client, "lk888_vision", side_effect=vision):
            result = self.client._run_replacement_visual_qc(job, segment, "/tmp/result.mp4")

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "principal_replacement_mismatch")
        self.assertIn("https://x/person-full.png", captured["media"])
        self.assertIn("principalReplacementMatch", captured["prompt"])
        self.assertIn("fullBodyAppearanceMatch", captured["prompt"])
        self.assertIn("发型、服装、体型和配饰", captured["prompt"])
        self.assertIn("职业马甲", captured["prompt"])

    def test_principal_segment_qc_runs_visual_check_without_product_reference(self):
        job = {
            "principalReplacementMode": "source_video_edit",
            "personReferenceUrls": ["https://x/person-full.png"],
            "outDir": tempfile.gettempdir(),
        }
        segment = {"index": 1}
        visual_qc = mock.Mock(return_value={
            "ok": True,
            "code": "ok",
            "checks": {"principalReplacement": "passed", "otherSubjects": "passed", "motion": "passed"},
        })
        with mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "_replacement_audio_qc", return_value={"ok": True}), \
                mock.patch.object(self.client, "_extract_replacement_qc_frames", return_value=["a", "b", "c"]), \
                mock.patch.object(self.client, "_run_replacement_visual_qc", visual_qc):
            result = self.client._run_replacement_segment_qc(job, segment, "/tmp/result.mp4")

        self.assertTrue(result["ok"])
        visual_qc.assert_called_once_with(job, segment, "/tmp/result.mp4")

    def test_segment_qc_skips_audio_validation(self):
        job = {"outDir": tempfile.gettempdir()}
        segment = {"index": 1}
        with mock.patch.object(
            self.client, "_breakdown_source_validation", return_value={"ok": True}
        ), mock.patch.object(
            self.client, "_replacement_audio_qc",
            side_effect=AssertionError("audio validation must be disabled"),
        ) as audio_qc, mock.patch.object(
            self.client, "_extract_replacement_qc_frames", return_value=["a", "b", "c"]
        ):
            result = self.client._run_replacement_segment_qc(
                job, segment, "/tmp/result.mp4"
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["checks"]["audio"], "skipped")
        audio_qc.assert_not_called()

    def test_principal_visual_qc_describes_only_media_that_were_provided(self):
        job = {
            "principalReplacementMode": "source_video_edit",
            "personReferenceUrls": ["https://x/person-full.png"],
            "temporaryMaterialIds": [],
        }
        captured = {}
        response = (
            '{"sourceProductVisible":true,"faceMatch":true,"productMatch":true,'
            '"logoTextReadable":true,"sceneMatch":true,"topicMatch":true,'
            '"roleMatch":true,"structureMatch":true,"severeDrift":false,'
            '"principalReplacementMatch":true,"otherSubjectsPreserved":true,'
            '"motionPreserved":true,"fullBodyAppearanceMatch":true,"reason":"ok"}'
        )

        def vision(prompt, media, max_tokens=500):
            captured["prompt"] = prompt
            captured["media"] = list(media)
            return response

        with mock.patch.object(self.client, "upload_asset_url", return_value=(
                "https://x/result.mp4", {"data": {"id": "temp-video"}}
        )), mock.patch.object(self.client, "lk888_vision", side_effect=vision):
            result = self.client._run_replacement_visual_qc(job, {"index": 1}, "/tmp/result.mp4")

        self.assertTrue(result["ok"])
        self.assertIn("未提供产品参考图且未提供场景参考图", captured["prompt"])
        self.assertNotIn("随后是主角人物全身参考图和场景参考图", captured["prompt"])

    def test_principal_segment_qc_hard_blocks_principal_visual_mismatch(self):
        job = {
            "principalReplacementMode": "source_video_edit",
            "productImageUrls": ["https://x/product.png"],
            "personReferenceUrls": ["https://x/person-full.png"],
            "outDir": tempfile.gettempdir(),
        }
        segment = {"index": 1}
        with mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "_replacement_audio_qc", return_value={"ok": True}), \
                mock.patch.object(self.client, "_extract_replacement_qc_frames", return_value=["a", "b", "c"]), \
                mock.patch.object(self.client, "_run_replacement_visual_qc", return_value={
                    "ok": False,
                    "code": "principal_other_subjects_changed",
                    "reason": "另一个人也被替换",
                    "checks": {"principalReplacement": "passed", "otherSubjects": "failed", "motion": "passed"},
                }):
            result = self.client._run_replacement_segment_qc(job, segment, "/tmp/result.mp4")

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "principal_other_subjects_changed")

    def test_standard_principal_appearance_mismatch_is_manual_review_warning(self):
        job = {
            "principalReplacementMode": "source_video_edit",
            "identityMode": "standard",
            "productImageUrls": ["https://x/product.png"],
            "personReferenceUrls": ["https://x/person-full.png"],
            "outDir": tempfile.gettempdir(),
        }
        segment = {"index": 1}
        visual = {
            "ok": False,
            "code": "principal_appearance_mismatch",
            "reason": "生成主角的服装与参考图不一致，未采用参考图中的职业套装，变成了黑色吊带裙",
            "checks": {
                "principalReplacement": "passed",
                "fullBodyAppearance": "failed",
                "otherSubjects": "passed",
                "motion": "passed",
            },
            "visualDriftQc": {"topicMatch": True, "roleMatch": True, "structureMatch": True, "severeDrift": False},
        }
        with mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "_replacement_audio_qc", return_value={"ok": True}), \
                mock.patch.object(self.client, "_extract_replacement_qc_frames", return_value=["a", "b", "c"]), \
                mock.patch.object(self.client, "_run_replacement_visual_qc", return_value=visual):
            result = self.client._run_replacement_segment_qc(job, segment, "/tmp/result.mp4")

        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "visual_qc_warning")
        self.assertEqual(segment["qcWarnings"][0]["code"], "principal_appearance_mismatch")
        self.assertEqual(segment["qcWarnings"][0]["severity"], "review_warning")

    def test_high_principal_appearance_mismatch_still_blocks(self):
        job = {
            "principalReplacementMode": "source_video_edit",
            "identityMode": "high",
            "productImageUrls": ["https://x/product.png"],
            "personReferenceUrls": ["https://x/person-full.png"],
            "outDir": tempfile.gettempdir(),
        }
        segment = {"index": 1}
        with mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "_replacement_audio_qc", return_value={"ok": True}), \
                mock.patch.object(self.client, "_extract_replacement_qc_frames", return_value=["a", "b", "c"]), \
                mock.patch.object(self.client, "_run_replacement_visual_qc", return_value={
                    "ok": False,
                    "code": "principal_appearance_mismatch",
                    "reason": "仍保留原片服装",
                    "checks": {"principalReplacement": "passed", "fullBodyAppearance": "failed",
                               "otherSubjects": "passed", "motion": "passed"},
                }):
            result = self.client._run_replacement_segment_qc(job, segment, "/tmp/result.mp4")

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "principal_appearance_mismatch")

    def test_video_edit_request_rejects_loopback_media_before_generation(self):
        job = {
            "productImageUrls": ["http://127.0.0.1:9080/product.png"],
            "sceneImageUrl": "http://127.0.0.1:9080/scene.png",
        }
        with self.assertRaisesRegex(RuntimeError, "video_replace_remote_media_required"):
            self.client._build_hybrid_video_edit_request(
                job, {"duration": 8}, "http://127.0.0.1:9080/source.mp4"
            )

    def test_drift_guard_config_defaults_are_production_safe(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            job = {}

            config = self.client._replacement_drift_guard_config(job)

        self.assertTrue(config["enabled"])
        self.assertTrue(config["preflightEnabled"])
        self.assertTrue(config["blockSevereDrift"])
        self.assertTrue(config["autoRetry"])
        self.assertEqual(config["maxRetries"], 1)

    def test_drift_guard_can_be_disabled_by_env(self):
        with mock.patch.dict(os.environ, {"VIDEO_REPLACE_DRIFT_GUARD": "0"}):
            job = {
                "driftGuardEnabled": True,
                "referencePreflightEnabled": True,
                "blockSevereDrift": True,
                "driftAutoRetry": True,
            }

            self.assertFalse(self.client._replacement_drift_guard_enabled(job))
            self.assertFalse(self.client._replacement_reference_preflight_enabled(job))
            self.assertFalse(self.client._replacement_block_severe_drift(job))
            self.assertFalse(self.client._replacement_drift_auto_retry_enabled(job))

    def test_replacement_prompt_frontloads_current_shot_breakdown_without_source_subtitles(self):
        analysis = {
            "report": (
                "## 内容总览\n汽车门店销售短视频。\n\n"
                "## 时间轴镜头拆解\n"
                "| 时间段 | 画面 | 人物 | 产品 | 动作 | 字幕/信息 | 道具 | 场景 | 节奏 |\n"
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
                "| 0.0-8.0 秒 | 女销售站在黑色车前右侧 | 女销售 | 黑色轿车 | 抬手指向车头并看镜头讲解 | 原片字幕：旧字幕不要出现 | 车钥匙 | 室内4S店 | 快节奏口播 |\n"
                "| 8.0-16.0 秒 | 方向盘和中控特写 | 无 | 黑色轿车 | 手转方向盘 | 原片字幕：第二段旧字幕 | 方向盘 | 车内 | 特写切换 |\n"
            ),
            "visual": "视觉说明里出现旧画面字幕",
            "frameNotes": "00:03 女销售在车前抬手",
            "ocr": {"text": "原视频OCR字幕不能进最终提示词"},
            "transcript": {"text": "原视频口播台词不能进最终提示词"},
        }
        segment = {"start": 0, "end": 8, "script": "用户新口播：凯美瑞优惠来了"}

        prompt = self.client._build_replacement_prompt(
            segment, analysis, "上传黑色轿车", "上传女销售"
        )

        self.assertIn("当前片段原片镜头约束", prompt)
        self.assertIn("抬手指向车头并看镜头讲解", prompt)
        self.assertIn("室内4S店", prompt)
        self.assertLess(prompt.index("当前片段原片镜头约束"), prompt.index("源视频锁定"))
        self.assertNotIn("原片字幕：旧字幕不要出现", prompt)
        self.assertNotIn("字幕/信息", prompt)
        self.assertNotIn("原视频OCR字幕不能进最终提示词", prompt)
        self.assertNotIn("原视频口播台词不能进最终提示词", prompt)

    def test_principal_prompt_keeps_user_script_as_only_dialogue_source_when_breakdown_has_old_subtitles(self):
        segment = {
            "duration": 8,
            "script": "用户新口播：凯美瑞优惠来了",
            "prompt": (
                "当前片段原片镜头约束：女销售站在车前抬手讲解。\n"
                "原片字幕：旧字幕不要出现。\n"
                "原视频口播台词不能进最终提示词。"
            ),
        }
        job = {
            "audioMode": "tts",
            "principalActor": {"status": "detected", "description": "女销售"},
            "personReferenceUrls": ["https://x/person.png"],
            "productImageUrls": ["https://x/car.png"],
        }

        prompt = self.client._build_principal_replacement_prompt(job, segment)

        self.assertIn("用户新口播：凯美瑞优惠来了", prompt)
        self.assertIn("当前片段原片镜头约束", prompt)
        self.assertNotIn("原片字幕：旧字幕不要出现", prompt)
        self.assertNotIn("原视频口播台词不能进最终提示词", prompt)
    def test_source_context_extracts_category_role_and_product(self):
        analysis = {
            "visual": "丰田门店里，一名男销售顾问介绍蓝牌新能源凯美瑞和赛那。",
            "frameNotes": "多帧出现汽车展厅、白色轿车、销售讲解。",
            "ocr": {"text": "蓝牌新能源 凯美瑞 广汽丰田"},
            "transcript": {"text": "老板你看这台蓝牌新能源车。"},
        }

        context = self.client._replacement_source_context_from_analysis(analysis)

        self.assertIn("丰田", context["evidence"])
        self.assertIn("丰田", context["sourceCategory"])
        self.assertIn("销售", context["sourceRole"])
        self.assertIn("凯美瑞", context["sourceProductCategory"])

    def test_source_context_uses_actual_breakdown_product_instead_of_car_fallback(self):
        analysis = {
            "report": (
                "## 内容总览\n"
                "视频类型：卫浴产品介绍型短视频 / B端备货推荐 / 展厅实拍口播带货素材。\n"
                "核心卖点：枪灰色高颜值、大平板置物、全铜水路、瀑布式下出水、6寸大手喷。\n"
            ),
            "visual": (
                "固定元素：\n"
                "* 人物：一位中年男性销售员/主播，身穿黑色短袖Polo衫。\n"
                "* 场景：卫浴产品实体展厅/门店，背景是展示墙，挂着多款淋浴花洒。\n"
                "* 主推产品（核心道具）：一套左侧墙面安装的枪灰色多功能淋浴花洒套装。\n"
            ),
            "ocr": {"text": "浴室颜值的天花板 大平板 全铜水路 6寸大手喷"},
            "transcript": {"text": "像这一款枪灰色淋浴，适合门店备货参考。"},
        }

        context = self.client._replacement_source_context_from_analysis(analysis)
        entities = self.client._replacement_source_entities_from_analysis(analysis)

        self.assertNotIn("汽车", context["sourceCategory"])
        self.assertNotIn("汽车", context["sourceProductCategory"])
        self.assertIn("卫浴", context["sourceCategory"])
        self.assertIn("花洒", context["sourceProductCategory"])
        self.assertTrue(any("花洒" in item["category"] for item in entities["products"]))
        self.assertTrue(any("卫浴" in item["type"] for item in entities["scenes"]))
        self.assertFalse(any("汽车" in item["type"] for item in entities["scenes"]))

    def test_reference_preflight_warns_for_face_context_mismatch(self):
        job = {
            "breakdownAnalysis": {"visual": "汽车展厅男销售介绍丰田新能源车"},
            "productImageUrls": ["https://x/car.png"],
            "faceSourceUrls": ["https://x/beauty-face.png"],
            "sceneImageUrl": "https://x/showroom.png",
            "noPersonMode": False,
        }
        raw = (
            '{"ok":true,"severity":"warning","blocked":false,'
            '"sourceCategory":"汽车销售","sourceRole":"销售顾问",'
            '"sourceProductCategory":"汽车",'
            '"referenceRisks":[{"type":"face_context_mismatch","url":"https://x/beauty-face.png","reason":"美妆主播上下文"}],'
            '"reason":"人物图只作为身份参考"}'
        )

        with mock.patch.object(self.client, "lk888_vision", return_value=raw):
            result = self.client._run_replacement_reference_preflight(job)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "warning")
        self.assertFalse(result["blocked"])
        self.assertEqual(result["referenceRisks"][0]["type"], "face_context_mismatch")

    def test_reference_preflight_prompt_checks_watermarks_and_dense_brand_text(self):
        job = {
            "breakdownAnalysis": {"visual": "卫浴展厅讲解花洒"},
            "productImageUrls": ["https://x/shower.png"],
            "faceSourceUrls": ["https://x/host.png"],
            "sceneImageUrl": "https://x/showroom.png",
        }
        raw = (
            '{"ok":true,"severity":"warning","blocked":false,'
            '"sourceCategory":"卫浴销售","sourceRole":"讲解员",'
            '"sourceProductCategory":"花洒","referenceRisks":[],"reason":"可继续"}'
        )
        prompts = []

        def fake_vision(prompt, *_args, **_kwargs):
            prompts.append(prompt)
            return raw

        with mock.patch.object(self.client, "lk888_vision", side_effect=fake_vision):
            result = self.client._run_replacement_reference_preflight(job)

        self.assertTrue(result["ok"])
        self.assertIn("水印", prompts[0])
        self.assertIn("百度百科", prompts[0])
        self.assertIn("电子屏幕", prompts[0])
        self.assertIn("促销海报", prompts[0])
        self.assertIn("Logo 过密", prompts[0])

    def test_reference_preflight_downgrades_person_background_block_to_warning(self):
        job = {
            "breakdownAnalysis": {"visual": "汽车展厅女销售介绍广汽丰田蓝牌新能源车"},
            "productImageUrls": ["https://x/car.png"],
            "faceSourceUrls": ["https://x/sales-face-front.png", "https://x/sales-face-left.png", "https://x/sales-face-right.png"],
            "sceneImageUrl": "https://x/showroom.png",
            "noPersonMode": False,
        }
        raw = (
            '{"ok":false,"severity":"blocking","blocked":true,'
            '"sourceCategory":"汽车销售","sourceRole":"女销售",'
            '"sourceProductCategory":"汽车",'
            '"referenceRisks":[{"type":"InvalidCharacterReference","url":"人物参考图(第3-6张)",'
            '"reason":"人物参考图中包含汽车销售行业制服、品牌Logo胸牌以及汽车展厅背景"}],'
            '"reason":"人物参考图包含明显的行业制服、品牌Logo与展厅背景，触发阻断规则。"}'
        )

        with mock.patch.object(self.client, "lk888_vision", return_value=raw):
            result = self.client._run_replacement_reference_preflight(job)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "warning")
        self.assertFalse(result["blocked"])
        self.assertEqual(result["code"], "ok")
        self.assertFalse(self.client._replacement_reference_preflight_blocks(job, result))
        self.assertIn("人物参考图", result["reason"])

    def test_reference_preflight_warns_for_product_category_mismatch(self):
        job = {
            "breakdownAnalysis": {"visual": "汽车展厅男销售介绍丰田新能源车"},
            "productImageUrls": ["https://x/lipstick.png"],
            "faceSourceUrls": ["https://x/face.png"],
            "sceneImageUrl": "https://x/showroom.png",
        }
        raw = (
            '{"ok":false,"severity":"blocking","blocked":true,'
            '"sourceCategory":"汽车销售","sourceRole":"销售顾问",'
            '"sourceProductCategory":"汽车",'
            '"referenceRisks":[{"type":"product_category_mismatch","url":"https://x/lipstick.png","reason":"产品图是美妆"}],'
            '"reason":"产品图与源视频产品类别冲突"}'
        )

        with mock.patch.object(self.client, "lk888_vision", return_value=raw):
            result = self.client._run_replacement_reference_preflight(job)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "warning")
        self.assertFalse(result["blocked"])
        self.assertFalse(self.client._replacement_reference_preflight_blocks(job, result))
        self.assertEqual(result["code"], "ok")

    def test_reference_preflight_degrades_when_vision_service_fails(self):
        job = {
            "breakdownAnalysis": {"visual": "汽车展厅男销售介绍丰田新能源车"},
            "productImageUrls": ["https://x/car.png"],
        }

        with mock.patch.object(self.client, "lk888_vision", side_effect=RuntimeError("timeout")), \
                mock.patch.object(self.client, "_replacement_error_id", return_value="err-preflight"):
            result = self.client._run_replacement_reference_preflight(job)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(result["errorId"], "err-preflight")

    def test_replacement_prompt_contains_source_lock_and_full_body_principal_rule(self):
        analysis = {
            "visual": "丰田门店男销售介绍新能源车",
            "ocr": {"text": "广汽丰田 凯美瑞"},
            "transcript": {"text": "今天讲这台车"},
        }
        segment = {"index": 1, "start": 0, "end": 8}

        prompt = self.client._build_replacement_prompt(
            segment, analysis, "uploaded car product", "authorized full-body presenter reference"
        )

        self.assertIn("源视频锁定", prompt)
        self.assertIn("人物参考图只用于新主角的脸、发型、服装、体型和配饰一致性", prompt)
        self.assertNotIn("人物图只提供身份和脸部", prompt)
        self.assertNotIn("服装、职业角色、动作、台词、站位和镜头关系按原片人物槽位", prompt)
        self.assertIn("保留原片内容类别", prompt)
        self.assertIn("新能源车", prompt)

    def test_source_entities_extract_original_slots_for_replacement(self):
        analysis = {
            "visual": "汽车展厅男销售站在白色新能源车旁讲解，背景是4S门店展厅。",
            "frameNotes": "00:02 男销售半身讲车；00:04 白色车身和车标特写；00:06 展厅前台。",
            "ocr": {"text": "广汽丰田 凯美瑞"},
            "transcript": {"text": "今天讲这台适合家用的车"},
        }

        entities = self.client._replacement_source_entities_from_analysis(analysis)

        self.assertEqual(entities["mode"], "source_entity_replacement")
        self.assertTrue(any("销售" in item["role"] for item in entities["people"]))
        self.assertTrue(any("车" in item["category"] for item in entities["products"]))
        self.assertTrue(any("展厅" in item["type"] for item in entities["scenes"]))
        self.assertIn("原片人物槽位", entities["replacementRules"])
        self.assertIn("未上传产品图时保留原片产品", entities["replacementRules"])
        self.assertIn("上传场景图时强制替换为上传场景", entities["replacementRules"])

    def test_hybrid_video_edit_prompt_uses_source_entity_replacement_slots(self):
        job = {
            "breakdownAnalysis": {"visual": "汽车展厅男销售介绍丰田新能源车"},
            "productImageUrls": ["https://x/car.png"],
            "faceSourceUrls": ["https://x/face-1.png"],
            "modelFaceUrl": "https://x/face-1.png",
            "sourceReplacementEntities": {
                "mode": "source_entity_replacement",
                "people": [{"slot": "person_1", "role": "销售顾问", "appearance": "原片男销售"}],
                "products": [{"slot": "product_1", "category": "汽车", "appearance": "原片白色新能源车"}],
                "scenes": [{"slot": "scene_1", "type": "汽车展厅", "appearance": "4S门店展厅"}],
                "replacementRules": "人物、产品、场景均按上传素材控制：未上传则保留原片对应槽位，上传则强制替换为上传素材。",
            },
        }
        segment = {"duration": 8, "prompt": "base prompt"}

        _model, payload = self.client._build_hybrid_video_edit_request(job, segment, "https://x/source.mp4")

        self.assertIn("源视频实体替换", payload["prompt"])
        self.assertIn("原片人物槽位", payload["prompt"])
        self.assertIn("替换为上传授权人物", payload["prompt"])
        self.assertIn("发型、服装、体型和配饰", payload["prompt"])
        self.assertNotIn("人物图只提供身份和脸部", payload["prompt"])
        self.assertIn("原片产品槽位", payload["prompt"])
        self.assertIn("替换为上传产品", payload["prompt"])
        self.assertIn("上传场景图时必须强制替换为上传场景", payload["prompt"])

    def test_hybrid_video_edit_prompt_preserves_source_category_over_face_context(self):
        job = {
            "breakdownAnalysis": {"visual": "汽车展厅男销售介绍丰田新能源车"},
            "productImageUrls": ["https://x/car.png"],
            "faceSourceUrls": ["https://x/beauty-face.png"],
            "modelFaceUrl": "https://x/beauty-face.png",
            "sceneImageUrl": "https://x/showroom.png",
            "referencePreflight": {
                "sourceCategory": "汽车销售",
                "sourceRole": "销售顾问",
                "sourceProductCategory": "汽车",
                "referenceRisks": [{"type": "face_context_mismatch", "reason": "美妆主播上下文"}],
            },
        }
        segment = {"duration": 8, "prompt": "base prompt"}

        _model, payload = self.client._build_hybrid_video_edit_request(job, segment, "https://x/source.mp4")

        self.assertIn("源视频锁定", payload["prompt"])
        self.assertIn("人物参考图只用于新主角的脸、发型、服装、体型和配饰一致性", payload["prompt"])
        self.assertIn("不复制参考图里的产品、行业", payload["prompt"])
        self.assertIn("汽车销售", payload["prompt"])
        self.assertIn("上传后必须以上传素材为准完成替换", payload["prompt"])

    def test_principal_scene_fallback_removes_scene_ref_but_keeps_product_ref(self):
        _model, payload = self.client._build_principal_video_edit_request(
            {
                "personReferenceUrls": ["https://cdn.example/person.jpg"],
                "productImageUrls": ["https://cdn.example/product.png"],
                "sceneImageUrl": "https://cdn.example/scene.png",
                "principalActor": {"status": "detected", "description": "main presenter"},
            },
            {"duration": 8, "prompt": "replace protagonist", "sceneFallbackMode": "ai_generated"},
            "https://cdn.example/source.mp4",
        )

        self.assertIn("https://cdn.example/product.png", payload["images"])
        self.assertNotIn("https://cdn.example/scene.png", payload["images"])
        self.assertIn("AI 生成场景", payload["prompt"])
        self.assertIn("产品必须保持上传产品", payload["prompt"])

    def test_visual_qc_skips_uploaded_scene_check_when_ai_scene_fallback_active(self):
        job = {
            "productImageUrls": ["https://x/car.png"],
            "modelFaceUrl": "https://x/face.png",
            "sceneImageUrl": "https://x/showroom.png",
            "scenePrompt": "bright indoor showroom",
            "temporaryMaterialIds": [],
        }
        segment = {
            "index": 2,
            "sourceSegmentUrl": "https://x/source-car-interior.mp4",
            "sceneFallbackMode": "ai_generated",
        }
        response = (
            '{"sourceProductVisible":true,"faceMatch":true,"productMatch":true,'
            '"logoTextReadable":true,"sceneMatch":false,'
            '"topicMatch":true,"roleMatch":true,"structureMatch":true,'
            '"severeDrift":false,"reason":"降级为AI生成门店场景"}'
        )
        with mock.patch.object(self.client, "upload_asset_url", return_value=(
                "https://x/result.mp4", {"data": {"id": "temp-video", "url": "https://x/result.mp4"}}
        )), mock.patch.object(self.client, "lk888_vision", return_value=response):
            result = self.client._run_replacement_visual_qc(job, segment, "/tmp/result.mp4")

        self.assertTrue(result["ok"])
        self.assertEqual(result["checks"]["scene"], "skipped")

    def test_scene_or_motion_mismatch_can_retry_with_ai_scene_when_product_passed(self):
        job = {"sceneImageUrl": "https://x/showroom.png", "productImageUrls": ["https://x/car.png"]}
        segment = {"index": 2}
        qc = {
            "ok": False,
            "code": "principal_motion_mismatch",
            "checks": {"product": "passed", "logoText": "passed", "scene": "failed"},
            "reason": "户外公路且未沿用方向盘动作",
        }

        self.assertTrue(self.client._replacement_can_retry_ai_scene_fallback(job, segment, qc))
        self.client._replacement_mark_ai_scene_fallback(job, segment, qc)
        self.assertEqual(segment["sceneFallbackMode"], "ai_generated")
        self.assertIn("户外公路", segment["sceneFallbackReason"])
        self.assertFalse(self.client._replacement_can_retry_ai_scene_fallback(job, segment, qc))
    def test_identity_mode_defaults_to_standard_and_uploaded_person_does_not_enable_facefusion(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            job = {
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
                "faceSourceUrls": ["https://x/f1.png", "https://x/f2.png", "https://x/f3.png"],
            }

            self.assertEqual(self.client._replacement_identity_mode(job), "standard")
            self.assertFalse(self.client._replacement_enable_facefusion(job))

    def test_identity_mode_high_enables_facefusion_and_old_jobs_remain_compatible(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(self.client._replacement_enable_facefusion({
                "identityMode": "high",
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            }))
            self.assertTrue(self.client._replacement_enable_facefusion({
                "enableFaceFusion": True,
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            }))
            self.assertTrue(self.client._replacement_enable_facefusion({
                "identityMode": "standard",
                "enableFaceFusion": True,
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            }))
            self.assertFalse(self.client._replacement_enable_facefusion({
                "identityMode": "standard",
                "enableFaceFusion": False,
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            }))
            self.assertFalse(self.client._replacement_enable_facefusion({
                "identityMode": "fast",
                "enableFaceFusion": True,
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            }))
            self.assertFalse(self.client._replacement_enable_facefusion({
                "identityMode": "high",
                "noPersonMode": True,
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            }))

    def test_principal_source_video_mode_never_enables_facefusion(self):
        job = {
            "principalReplacementMode": "source_video_edit",
            "identityMode": "high",
            "enableFaceFusion": True,
            "faceSourcePaths": ["/tmp/f1.jpg"],
        }

        self.assertFalse(self.client._replacement_enable_facefusion(job))
        self.assertFalse(self.client._replacement_enable_digital_human_facefusion(
            job, {"segmentType": "talking"}))

    def test_digital_human_facefusion_only_runs_in_high_identity_mode(self):
        segment = {"segmentType": "talking"}
        with mock.patch.dict(os.environ, {"VIDEO_REPLACE_DIGITAL_HUMAN_FACEFUSION": "1"}, clear=True):
            self.assertFalse(self.client._replacement_enable_digital_human_facefusion({
                "identityMode": "standard",
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            }, segment))
            self.assertTrue(self.client._replacement_enable_digital_human_facefusion({
                "identityMode": "high",
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            }, segment))

    def test_facefusion_preflight_requires_bin_models_and_license(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            result = self.client._facefusion_preflight()

        self.assertFalse(result["ok"])
        self.assertIn("facefusion_not_configured", result["errors"])
        self.assertIn("facefusion_license_missing", result["errors"])

    def test_facefusion_runs_without_shell_and_keeps_target_reference(self):
        with tempfile.TemporaryDirectory() as td:
            binary = Path(td) / "facefusion"
            model_dir = Path(td) / "models"
            input_video = Path(td) / "input.mp4"
            target_ref = Path(td) / "target.jpg"
            source_faces = [Path(td) / ("source_%d.jpg" % i) for i in range(3)]
            output = Path(td) / "output.mp4"
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            binary.chmod(0o755)
            model_dir.mkdir()
            input_video.write_bytes(b"video")
            target_ref.write_bytes(b"face")
            for face in source_faces:
                face.write_bytes(b"face")
            config = {
                "bin": str(binary),
                "modelDir": str(model_dir),
                "licenseRef": "commercial-license-2026",
                "providers": ["coreml", "cpu"],
            }

            def fake_run(args, **kwargs):
                output.write_bytes(b"swapped-video-placeholder")
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

            with mock.patch.object(self.client.subprocess, "run", side_effect=fake_run) as run:
                result = self.client._run_facefusion(
                    str(input_video),
                    str(output),
                    [str(p) for p in source_faces],
                    str(target_ref),
                    config=config,
                )

        self.assertEqual(result, str(output))
        args = run.call_args.args[0]
        self.assertIsInstance(args, list)
        self.assertIn("--reference-face-path", args)
        self.assertIn(str(target_ref), args)
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_sensitive_material_cleanup_deletes_center_materials(self):
        job = {"sensitiveMaterialIds": ["face-1", "face-2"], "sensitiveCleanup": {}}
        with mock.patch.object(self.client, "api", return_value=(200, {"ok": True})) as api:
            result = self.client._cleanup_replacement_sensitive_materials(job)

        self.assertTrue(result["ok"])
        self.assertEqual(result["deleted"], ["face-1", "face-2"])
        self.assertEqual(job["sensitiveMaterialIds"], [])
        self.assertEqual(api.call_count, 2)

    def test_audio_qc_accepts_tone_and_rejects_silence(self):
        with tempfile.TemporaryDirectory() as td:
            tone = Path(td) / "tone.mp4"
            silence = Path(td) / "silence.mp4"
            make_tone_video(self.client, tone)
            subprocess.run([
                self.client._ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=black:s=160x284:r=30:d=1",
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(silence),
            ], check=True, capture_output=True)

            tone_result = self.client._replacement_audio_qc(str(tone))
            silence_result = self.client._replacement_audio_qc(str(silence))

        self.assertTrue(tone_result["ok"])
        self.assertGreater(tone_result["meanVolumeDb"], -45.0)
        self.assertFalse(silence_result["ok"])
        self.assertEqual(silence_result["code"], "audio_silent")

    def test_replacement_concat_preserves_audio_without_validating_output_audio(self):
        paths = ["/tmp/one.mp4", "/tmp/two.mp4"]
        with mock.patch.object(self.client.os.path, "isfile", return_value=True), \
                mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "mix_clips", return_value="/tmp/final.mp4") as mix, \
                mock.patch.object(
                    self.client, "_replacement_audio_qc",
                    side_effect=AssertionError("audio validation must be disabled"),
                ) as audio_qc:
            result = self.client._concat_replacement_segments(paths, "/tmp/final.mp4")

        self.assertEqual(result, "/tmp/final.mp4")
        mix.assert_called_once_with(paths, "/tmp/final.mp4", size_label="竖屏 9:16", preserve_source_audio=True)
        audio_qc.assert_not_called()

    def test_replacement_subtitle_ass_uses_segment_scripts_and_readable_style(self):
        with tempfile.TemporaryDirectory() as td:
            job = {
                "outDir": td,
                "segments": [
                    {"index": 1, "start": 0, "end": 2.5, "script": "第一句中文口播"},
                    {"index": 2, "start": 2.5, "end": 5, "script": "第二句中文口播更长一些"},
                ],
            }

            result = self.client._write_replacement_subtitle_ass(job, os.path.join(td, "final.mp4"))
            text = Path(result["path"]).read_text(encoding="utf-8-sig")

        self.assertTrue(result["ok"])
        self.assertIn("Style: Default,Microsoft YaHei", text)
        self.assertIn("Dialogue: 0,0:00:00.00,0:00:02.50", text)
        self.assertIn("第一句中文口播", text)
        self.assertIn("Dialogue: 0,0:00:02.50,0:00:05.00", text)
        self.assertIn("第二句中文口播更长一些", text)
        self.assertIn("&H00000000", text)

    def test_replacement_subtitle_events_follow_actual_segment_video_durations(self):
        job = {
            "segments": [
                {"index": 1, "start": 0, "end": 8, "duration": 8, "script": "第一句", "videoPath": "/tmp/seg1.mp4"},
                {"index": 2, "start": 8, "end": 16, "duration": 8, "script": "第二句", "videoPath": "/tmp/seg2.mp4"},
            ],
        }

        with mock.patch.object(self.client, "_probe_video", side_effect=[
            {"duration": 3.0},
            {"duration": 5.0},
        ]):
            events = self.client._replacement_subtitle_events(job)

        self.assertEqual(events[0]["start"], 0.0)
        self.assertEqual(events[0]["end"], 3.0)
        self.assertEqual(events[1]["start"], 3.0)
        self.assertEqual(events[1]["end"], 8.0)

    def test_replacement_final_video_burns_script_subtitles_before_asset_save(self):
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw.mp4"
            subtitled = Path(td) / "subtitled.mp4"
            raw.write_bytes(b"raw")
            job = {
                "outDir": td,
                "segments": [{"index": 1, "start": 0, "end": 2, "script": "清晰中文字幕"}],
            }

            with mock.patch.object(self.client, "_concat_replacement_segments", return_value=str(raw)) as concat, \
                    mock.patch.object(self.client, "_burn_replacement_subtitles", return_value={
                        "ok": True,
                        "videoPath": str(subtitled),
                        "subtitlePath": str(Path(td) / "final.ass"),
                        "mode": "burned",
                    }) as burn:
                result = self.client._prepare_replacement_final_video(job, ["/tmp/seg.mp4"], str(raw))

        concat.assert_called_once_with(["/tmp/seg.mp4"], str(raw))
        burn.assert_called_once_with(job, str(raw))
        self.assertEqual(result, str(subtitled))
        self.assertEqual(job["rawOutputPath"], str(raw))
        self.assertEqual(job["subtitleStatus"], "burned")
        self.assertEqual(job["subtitlePath"], str(Path(td) / "final.ass"))

    def test_uploaded_audio_mode_replaces_final_audio_after_subtitles(self):
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw.mp4"
            subtitled = Path(td) / "subtitled.mp4"
            voiced = Path(td) / "voiced.mp4"
            raw.write_bytes(b"raw")
            job = {
                "outDir": td,
                "audioMode": "uploaded",
                "replacementAudioPath": str(Path(td) / "voice.mp3"),
                "replacementAudioUrl": "https://x/voice.mp3",
                "segments": [{"index": 1, "start": 0, "end": 2, "script": "清晰中文字幕"}],
            }

            with mock.patch.object(self.client, "_concat_replacement_segments", return_value=str(raw)) as concat, \
                    mock.patch.object(self.client, "_burn_replacement_subtitles", return_value={
                        "ok": True,
                        "videoPath": str(subtitled),
                        "subtitlePath": str(Path(td) / "final.ass"),
                        "mode": "burned",
                    }) as burn, \
                    mock.patch.object(self.client, "_replace_replacement_final_audio", create=True,
                                      return_value=str(voiced)) as replace_audio:
                result = self.client._prepare_replacement_final_video(job, ["/tmp/seg.mp4"], str(raw))

        concat.assert_called_once_with(["/tmp/seg.mp4"], str(raw))
        burn.assert_called_once_with(job, str(raw))
        replace_audio.assert_called_once_with(job, str(subtitled))
        self.assertEqual(result, str(voiced))
        self.assertEqual(job["finalAudioMode"], "uploaded")

    def test_non_talking_segment_defaults_to_remote_edit_without_facefusion(self):
        segment = {
            "index": 1,
            "segmentType": "non_talking",
            "duration": 8,
            "prompt": "preserve motion",
            "sourceSegmentPath": "/tmp/source-segment.mp4",
        }
        job = {
            "outDir": "/tmp/job",
            "productImageUrls": ["https://x/product.png"],
            "modelFaceUrl": "https://x/face-front.png",
            "sceneImageUrl": "https://x/scene.png",
        }
        order = []

        def upload(path, title, kind):
            order.append("upload")
            return "https://x/source.mp4", {"id": "source-temp"}

        captured_payload = {}

        def media(model, payload, exts, progress=None, tries=110):
            order.append("edit")
            captured_payload.update(payload)
            return "https://x/edited.mp4"

        def download(url, path):
            order.append("download")
            return path

        def facefusion(input_path, output_path, faces, target, config=None):
            order.append("facefusion")
            return output_path

        with mock.patch.object(self.client, "upload_asset_url", side_effect=upload), \
                mock.patch.object(self.client, "lk888_media_task", side_effect=media), \
                mock.patch.object(self.client, "_wf_download", side_effect=download), \
                mock.patch.object(self.client, "_run_facefusion", side_effect=facefusion), \
                mock.patch.object(self.client, "_ensure_segment_audio", side_effect=lambda before, after: order.append("audio") or after), \
                mock.patch.object(self.client, "_run_replacement_segment_qc", return_value={"ok": True, "frames": ["a.jpg"]}), \
                mock.patch.object(self.client, "_save_replacement_job"):
            path = self.client._run_hybrid_non_talking_segment(job, segment)

        self.assertEqual(order, ["upload", "edit", "download"])
        self.assertTrue(path.endswith("edited_01.mp4"))
        self.assertEqual(segment["sourceSegmentUrl"], "https://x/source.mp4")
        self.assertEqual(segment["sourceSegmentMaterialId"], "source-temp")
        self.assertIn("https://x/face-front.png", captured_payload["image_urls"])
        self.assertNotIn("source_video_url", captured_payload)
        self.assertNotIn("model_candidates", captured_payload)
        self.assertEqual(segment["sourceSegmentUrl"], "https://x/source.mp4")
        self.assertEqual(segment["editedVideoPath"], "/tmp/job/edited_01.mp4")
        self.assertEqual(segment["faceSwapPath"], "")
        self.assertEqual(segment["videoPath"], "/tmp/job/edited_01.mp4")
        self.assertEqual(segment["audioStatus"], "passed")
        self.assertEqual(segment["qcStatus"], "passed")

    def test_non_talking_segment_uploads_subtitle_safe_source_but_keeps_original_audio(self):
        segment = {
            "index": 1,
            "segmentType": "non_talking",
            "duration": 8,
            "prompt": "preserve motion",
            "sourceSegmentPath": "/tmp/source-segment.mp4",
        }
        job = {
            "outDir": "/tmp/job",
            "productImageUrls": ["https://x/product.png"],
            "modelFaceUrl": "https://x/face-front.png",
        }
        uploads = []

        def upload(path, title, kind):
            uploads.append((path, title, kind))
            return "https://x/source-safe.mp4", {"id": "source-safe"}

        with mock.patch.object(self.client, "_prepare_subtitle_safe_source_segment",
                               return_value="/tmp/source-segment.subtitle-safe.mp4") as prepare_safe, \
                mock.patch.object(self.client, "upload_asset_url", side_effect=upload), \
                mock.patch.object(self.client, "lk888_media_task", return_value="https://x/edited.mp4"), \
                mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: path), \
                mock.patch.object(self.client, "_ensure_segment_audio", side_effect=lambda before, after: after) as ensure_audio, \
                mock.patch.object(self.client, "_run_replacement_segment_qc", return_value={"ok": True, "frames": ["a.jpg"]}), \
                mock.patch.object(self.client, "_save_replacement_job"):
            self.client._run_hybrid_non_talking_segment(job, segment)

        prepare_safe.assert_called_once_with(job, segment, "/tmp/source-segment.mp4")
        self.assertEqual(uploads[0][0], "/tmp/source-segment.subtitle-safe.mp4")
        self.assertIn("字幕安全", uploads[0][1])
        self.assertEqual(segment["sourceSegmentUploadPath"], "/tmp/source-segment.subtitle-safe.mp4")
        self.assertEqual(segment["sourceSegmentPath"], "/tmp/source-segment.mp4")
        ensure_audio.assert_not_called()

    def test_prepare_subtitle_safe_source_segment_outputs_valid_masked_video(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.mp4"
            make_tone_video(self.client, source, duration=1.0)
            segment = {"index": 1}

            safe_path = self.client._prepare_subtitle_safe_source_segment(
                {"outDir": td}, segment, str(source))

            self.assertNotEqual(safe_path, str(source))
            self.assertTrue(Path(safe_path).exists())
            self.assertEqual(segment["sourceSegmentSubtitleSafeStatus"], "masked")
            validation = self.client.validate_video_file(safe_path)
            self.assertTrue(validation["ok"])
            self.assertTrue(validation["hasAudio"])

    def test_non_talking_segment_uploads_action_frames_when_action_control_enabled(self):
        segment = {
            "index": 1,
            "segmentType": "non_talking",
            "duration": 8,
            "prompt": "preserve motion",
            "sourceSegmentPath": "/tmp/source-segment.mp4",
        }
        job = {
            "actionControlEnabled": True,
            "productAnchorEnabled": False,
            "outDir": "/tmp/job",
            "sourceVideoPath": "/tmp/source.mp4",
            "productImageUrls": ["https://x/product.png"],
            "modelFaceUrl": "https://x/face-front.png",
        }
        uploads = []
        captured_payload = {}

        def upload(path, title, kind):
            uploads.append((path, title, kind))
            if kind == "video":
                return "https://x/source.mp4", {"id": "source-temp"}
            return "https://x/%s.jpg" % Path(path).stem, {"id": "mat-%s" % Path(path).stem}

        def media(_model, payload, _exts, progress=None, tries=110):
            captured_payload.update(payload)
            return "https://x/edited.mp4"

        with mock.patch.object(self.client, "_extract_replacement_action_frames", return_value=["/tmp/action_01.jpg", "/tmp/action_02.jpg"]), \
                mock.patch.object(self.client, "upload_asset_url", side_effect=upload), \
                mock.patch.object(self.client, "lk888_media_task", side_effect=media), \
                mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: path), \
                mock.patch.object(self.client, "_ensure_segment_audio", side_effect=lambda before, after: after), \
                mock.patch.object(self.client, "_run_replacement_segment_qc", return_value={"ok": True, "frames": ["a.jpg"]}), \
                mock.patch.object(self.client, "_save_replacement_job"):
            self.client._run_hybrid_non_talking_segment(job, segment)

        self.assertEqual([item[2] for item in uploads], ["video", "image", "image"])
        self.assertEqual(segment["actionFrameUrls"], ["https://x/action_01.jpg", "https://x/action_02.jpg"])
        self.assertIn("https://x/action_01.jpg", captured_payload["image_urls"])
        self.assertIn("https://x/action_02.jpg", captured_payload["image_urls"])
        self.assertIn("mat-action_01", job["temporaryMaterialIds"])

    def test_non_talking_segment_falls_back_when_action_frame_upload_fails(self):
        segment = {
            "index": 1,
            "segmentType": "non_talking",
            "duration": 8,
            "prompt": "preserve motion",
            "sourceSegmentPath": "/tmp/source-segment.mp4",
        }
        job = {
            "actionControlEnabled": True,
            "outDir": "/tmp/job",
            "sourceVideoPath": "/tmp/source.mp4",
            "productImageUrls": ["https://x/product.png"],
            "modelFaceUrl": "https://x/face-front.png",
        }
        captured_payload = {}

        def upload(_path, _title, kind):
            if kind == "video":
                return "https://x/source.mp4", {"id": "source-temp"}
            raise RuntimeError("upload failed")

        def media(_model, payload, _exts, progress=None, tries=110):
            captured_payload.update(payload)
            return "https://x/edited.mp4"

        with mock.patch.object(self.client, "_extract_replacement_action_frames", return_value=["/tmp/action_01.jpg"]), \
                mock.patch.object(self.client, "upload_asset_url", side_effect=upload), \
                mock.patch.object(self.client, "lk888_media_task", side_effect=media), \
                mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: path), \
                mock.patch.object(self.client, "_ensure_segment_audio", side_effect=lambda before, after: after), \
                mock.patch.object(self.client, "_run_replacement_segment_qc", return_value={"ok": True, "frames": ["a.jpg"]}), \
                mock.patch.object(self.client, "_save_replacement_job"):
            self.client._run_hybrid_non_talking_segment(job, segment)

        self.assertEqual(segment["actionFrameUrls"], [])
        self.assertIn("upload failed", segment["actionControlWarning"])
        self.assertNotIn("https://x/action_01.jpg", captured_payload["image_urls"])

    def test_prepare_continuity_frame_uploads_previous_segment_review_frame(self):
        with tempfile.TemporaryDirectory() as td:
            previous_frame = Path(td) / "previous_last.jpg"
            previous_frame.write_bytes(b"jpg-bytes")
            job = {
                "segments": [
                    {"index": 1, "qcFrames": ["missing.jpg", str(previous_frame)]},
                    {"index": 2},
                ],
            }
            segment = job["segments"][1]

            with mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/previous_last.jpg", {"id": "mat-prev"})):
                url = self.client._prepare_replacement_continuity_frame_ref(job, segment)

        self.assertEqual(url, "https://x/previous_last.jpg")
        self.assertEqual(segment["continuityFrameUrl"], "https://x/previous_last.jpg")
        self.assertIn("mat-prev", job["temporaryMaterialIds"])

    def test_non_talking_segment_falls_back_to_next_reference_model_and_records_remote_error(self):
        segment = {
            "index": 1,
            "segmentType": "non_talking",
            "duration": 8,
            "prompt": "preserve motion",
            "sourceSegmentPath": "/tmp/source-segment.mp4",
        }
        job = {
            "outDir": "/tmp/job",
            "productImageUrls": ["https://x/product.png"],
            "modelFaceUrl": "https://x/face-front.png",
            "faceSourceUrls": [],
        }
        models = []

        def media(model, payload, exts, progress=None, tries=110):
            models.append(model)
            if model == "viduq3-turbo-cankaosheng":
                raise RuntimeError("上游队列繁忙")
            return "https://x/edited.mp4"

        with mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/source.mp4", {"id": "source-temp"})), \
                mock.patch.object(self.client, "lk888_media_task", side_effect=media), \
                mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: path), \
                mock.patch.object(self.client, "_ensure_segment_audio", side_effect=lambda before, after: after), \
                mock.patch.object(self.client, "_run_replacement_segment_qc", return_value={"ok": True, "frames": ["a.jpg"]}), \
                mock.patch.object(self.client, "_save_replacement_job"), \
                mock.patch.object(self.client, "_replacement_error_id", return_value="err-remote-first"):
            path = self.client._run_hybrid_non_talking_segment(job, segment)

        self.assertEqual(models[:2], ["viduq3-turbo-cankaosheng", "wan2.7-cankaosheng"])
        self.assertTrue(path.endswith("edited_01.mp4"))
        self.assertEqual(segment["model"], "wan2.7-cankaosheng")
        self.assertEqual(segment["remoteError"], "")
        self.assertEqual(segment["remoteErrorId"], "")
        self.assertEqual(segment["remoteModelFallbacks"][0]["model"], "viduq3-turbo-cankaosheng")
        self.assertEqual(segment["remoteModelFallbacks"][0]["error"], "上游队列繁忙")

    def test_segment_status_text_hides_remote_fallback_error_after_success(self):
        job = {"segments": [{"index": 1}]}
        segment = {
            "index": 1,
            "status": "done",
            "model": "happyhorse-video-edit",
            "videoPath": "/tmp/edited_01.mp4",
            "audioStatus": "passed",
            "qcStatus": "passed",
            "error": "",
            "errorId": "",
            "remoteErrorId": "err-remote-first",
            "remoteError": "kwvideo-v2-quannengcankao 生成失败:status=错误",
        }

        text = self.client._replacement_segment_status_text(job, segment)
        display_error = self.client._replacement_segment_display_error(segment)

        self.assertIn("片段完成", text)
        self.assertNotIn("错误编号 err-remote-first", text)
        self.assertEqual(display_error, "")

    def test_principal_segment_failure_stops_without_reference_model_fallback(self):
        segment = {
            "index": 1,
            "segmentType": "non_talking",
            "duration": 8,
            "prompt": "preserve source motion",
            "sourceSegmentPath": "/tmp/source-segment.mp4",
        }
        job = {
            "id": "principal-job",
            "outDir": "/tmp/job",
            "principalReplacementMode": "source_video_edit",
            "principalActor": {"status": "detected", "description": "main presenter"},
            "personReferenceUrls": ["https://x/person.jpg"],
            "model": "happyhorse-video-edit",
        }
        models = []
        stages = []
        error_events = []

        def media(model, _payload, _exts, progress=None, tries=110):
            models.append(model)
            raise RuntimeError("upstream rejected edit")

        def error_id(event, _exc, **_ctx):
            error_events.append(event)
            return "err-principal"

        self.client._REPLACEMENT_PROGRESS_CALLBACKS[job["id"]] = (
            lambda _segment, stage, message, prompt=None: stages.append((stage, message)))
        try:
            with mock.patch.object(
                    self.client, "upload_asset_url",
                    return_value=("https://x/source.mp4", {"id": "source-temp"})), \
                    mock.patch.object(self.client, "lk888_media_task", side_effect=media), \
                    mock.patch.object(self.client, "_save_replacement_job"), \
                    mock.patch.object(self.client, "_replacement_error_id", side_effect=error_id):
                with self.assertRaisesRegex(RuntimeError, "principal_video_edit_failed"):
                    self.client._run_hybrid_non_talking_segment(job, segment)
        finally:
            self.client._REPLACEMENT_PROGRESS_CALLBACKS.pop(job["id"], None)

        self.assertEqual(models, ["happyhorse-video-edit"])
        self.assertIn("video", segment["remoteRequestFields"])
        self.assertIn("images", segment["remoteRequestFields"])
        self.assertNotIn("https://x/source.mp4", segment["remoteRequestFields"])
        self.assertIn("principal_video_edit_failed", error_events)
        self.assertTrue(any(stage == "principal_video_edit" for stage, _message in stages))

    def test_principal_segment_defaults_to_auto_generated_audio_without_source_mux(self):
        segment = {
            "index": 1,
            "segmentType": "non_talking",
            "duration": 8,
            "sourceSegmentPath": "/tmp/source-segment.mp4",
        }
        job = {
            "outDir": "/tmp/job",
            "principalReplacementMode": "source_video_edit",
            "principalActor": {"status": "detected", "description": "main presenter"},
            "personReferenceUrls": ["https://x/person.jpg"],
        }

        with mock.patch.object(
                self.client, "upload_asset_url",
                return_value=("https://x/source.mp4", {"id": "source-temp"})), \
                mock.patch.object(self.client, "lk888_media_task", return_value="https://x/edited.mp4"), \
                mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: path), \
                mock.patch.object(self.client, "_replace_segment_audio_from_source") as replace_audio, \
                mock.patch.object(self.client, "_ensure_segment_audio") as ensure_audio, \
                mock.patch.object(self.client, "_run_replacement_segment_qc", return_value={
                    "ok": True, "frames": ["a.jpg"], "checks": {"media": "passed", "audio": "passed"},
                }), \
                mock.patch.object(self.client, "_save_replacement_job"):
            path = self.client._run_hybrid_non_talking_segment(job, segment)

        replace_audio.assert_not_called()
        ensure_audio.assert_not_called()
        self.assertEqual(segment["audioMode"], "auto")
        self.assertEqual(segment["audioStatus"], "passed")
        self.assertEqual(path, "/tmp/job/edited_01.mp4")

    def test_non_talking_segment_retries_once_on_severe_drift(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.mp4"
            edited = Path(td) / "edited.mp4"
            make_tone_video(self.client, source, duration=1)
            make_tone_video(self.client, edited, duration=1)
            job = {
                "id": "job-drift-retry",
                "identityMode": "standard",
                "outDir": td,
                "sourceVideoPath": str(source),
                "segments": [],
                "productImageUrls": ["https://x/car.png"],
                "modelFaceUrl": "https://x/face.png",
            }
            segment = {"index": 1, "start": 0, "end": 1, "duration": 1, "audioStatus": "pending", "qcStatus": "pending"}
            job["segments"] = [segment]
            qc_results = [
                {"ok": False, "code": "visual_drift_blocked", "frames": ["a", "b", "c"],
                 "checks": {"media": "passed", "audio": "passed"}, "retryableDrift": True,
                 "visual": {"visualDriftQc": {"severeDrift": True}}},
                {"ok": True, "code": "ok", "frames": ["a", "b", "c"],
                 "checks": {"media": "passed", "audio": "passed"}},
            ]

            with mock.patch.object(self.client, "_extract_replacement_segment", side_effect=lambda _src, _seg, out: shutil.copyfile(source, out)), \
                    mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/source.mp4", {})), \
                    mock.patch.object(self.client, "lk888_media_task", return_value="https://x/edited.mp4") as media_task, \
                    mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: shutil.copyfile(edited, path)), \
                    mock.patch.object(self.client, "_ensure_segment_audio", return_value=None), \
                    mock.patch.object(self.client, "_run_replacement_segment_qc", side_effect=qc_results), \
                    mock.patch.object(self.client, "_save_replacement_job", return_value=str(Path(td) / "replacement_job.json")):
                path = self.client._run_hybrid_non_talking_segment(job, segment)

        self.assertTrue(path.endswith("edited_01.mp4"))
        self.assertEqual(media_task.call_count, 2)
        self.assertEqual(segment["driftRetryCount"], 1)
        self.assertEqual(segment["retryReason"], "visual_drift_blocked")
        self.assertEqual(segment["qcStatus"], "passed")

    def test_non_talking_high_mode_drift_retry_emits_segment_stage(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.mp4"
            edited = Path(td) / "edited.mp4"
            make_tone_video(self.client, source, duration=1)
            make_tone_video(self.client, edited, duration=1)
            job = {
                "id": "job-high-drift-retry",
                "identityMode": "high",
                "enableFaceFusion": True,
                "outDir": td,
                "sourceVideoPath": str(source),
                "segments": [],
                "productImageUrls": ["https://x/car.png"],
                "modelFaceUrl": "https://x/face.png",
                "faceSourcePaths": [str(source), str(source), str(source)],
                "targetFaceReferencePath": str(source),
            }
            segment = {"index": 1, "start": 0, "end": 1, "duration": 1}
            job["segments"] = [segment]
            qc_results = [
                {"ok": False, "code": "visual_drift_blocked", "frames": ["a", "b", "c"],
                 "checks": {"media": "passed", "audio": "passed"}, "retryableDrift": True,
                 "visual": {"visualDriftQc": {"severeDrift": True}}},
                {"ok": True, "code": "ok", "frames": ["a", "b", "c"],
                 "checks": {"media": "passed", "audio": "passed"}},
            ]
            events = []

            def progress(seg, stage, message, prompt=None):
                events.append((seg.get("index"), stage, message))

            def facefusion(_input, output, _faces, _target, config=None):
                shutil.copyfile(edited, output)
                return output

            self.client._REPLACEMENT_PROGRESS_CALLBACKS[job["id"]] = progress
            try:
                with mock.patch.object(self.client, "_extract_replacement_segment", side_effect=lambda _src, _seg, out: shutil.copyfile(source, out)), \
                        mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/source.mp4", {})), \
                        mock.patch.object(self.client, "lk888_media_task", return_value="https://x/edited.mp4"), \
                        mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: shutil.copyfile(edited, path)), \
                        mock.patch.object(self.client, "_run_facefusion", side_effect=facefusion), \
                        mock.patch.object(self.client, "_ensure_segment_audio", return_value=None), \
                        mock.patch.object(self.client, "_run_replacement_segment_qc", side_effect=qc_results), \
                        mock.patch.object(self.client, "_save_replacement_job", return_value=str(Path(td) / "replacement_job.json")):
                    path = self.client._run_hybrid_non_talking_segment(job, segment)
            finally:
                self.client._REPLACEMENT_PROGRESS_CALLBACKS.pop(job["id"], None)

        self.assertTrue(path.endswith("face_swap_01.mp4"))
        self.assertIn((1, "video_edit", "生成片段 1：主题跑偏，正在强化原视频锁定后重试"), events)
        self.assertEqual(segment["driftRetryCount"], 1)

    def test_non_talking_segment_fails_after_drift_retry_exhausted(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.mp4"
            edited = Path(td) / "edited.mp4"
            make_tone_video(self.client, source, duration=1)
            make_tone_video(self.client, edited, duration=1)
            job = {
                "id": "job-drift-exhausted",
                "identityMode": "standard",
                "outDir": td,
                "sourceVideoPath": str(source),
                "segments": [],
                "productImageUrls": ["https://x/car.png"],
                "modelFaceUrl": "https://x/face.png",
            }
            segment = {"index": 1, "start": 0, "end": 1, "duration": 1, "audioStatus": "pending", "qcStatus": "pending"}
            job["segments"] = [segment]
            qc = {"ok": False, "code": "visual_drift_blocked", "frames": ["a", "b", "c"],
                  "checks": {"media": "passed", "audio": "passed"}, "retryableDrift": True,
                  "visual": {"visualDriftQc": {"severeDrift": True}}}

            with mock.patch.object(self.client, "_extract_replacement_segment", side_effect=lambda _src, _seg, out: shutil.copyfile(source, out)), \
                    mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/source.mp4", {})), \
                    mock.patch.object(self.client, "lk888_media_task", return_value="https://x/edited.mp4"), \
                    mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: shutil.copyfile(edited, path)), \
                    mock.patch.object(self.client, "_ensure_segment_audio", return_value=None), \
                    mock.patch.object(self.client, "_run_replacement_segment_qc", side_effect=[qc, qc]), \
                    mock.patch.object(self.client, "_save_replacement_job", return_value=str(Path(td) / "replacement_job.json")):
                with self.assertRaisesRegex(RuntimeError, "visual_drift_retry_exhausted"):
                    self.client._run_hybrid_non_talking_segment(job, segment)

        self.assertEqual(segment["status"], "failed")
        self.assertEqual(segment["qcStatus"], "failed")
        self.assertEqual(segment["blockedReason"], "visual_drift_retry_exhausted")

    def test_non_talking_segment_runs_facefusion_only_in_high_identity_mode(self):
        segment = {
            "index": 1,
            "segmentType": "non_talking",
            "duration": 8,
            "prompt": "preserve motion",
            "sourceSegmentPath": "/tmp/source-segment.mp4",
        }
        job = {
            "identityMode": "high",
            "enableFaceFusion": True,
            "outDir": "/tmp/job",
            "productImageUrls": ["https://x/product.png"],
            "sceneImageUrl": "https://x/scene.png",
            "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            "targetFaceReferencePath": "/tmp/target.jpg",
            "facefusionConfig": {"bin": "/tmp/ff", "modelDir": "/tmp/models", "licenseRef": "license", "providers": ["cpu"]},
        }
        order = []

        def facefusion(input_path, output_path, faces, target, config=None):
            order.append("facefusion")
            return output_path

        with mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/source.mp4", {"id": "source-temp"})), \
                mock.patch.object(self.client, "lk888_media_task", return_value="https://x/edited.mp4"), \
                mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: path), \
                mock.patch.object(self.client, "_run_facefusion", side_effect=facefusion), \
                mock.patch.object(self.client, "_ensure_segment_audio", side_effect=lambda before, after: order.append("audio") or after), \
                mock.patch.object(self.client, "_run_replacement_segment_qc", return_value={"ok": True, "frames": ["a.jpg"]}), \
                mock.patch.object(self.client, "_save_replacement_job"):
            path = self.client._run_hybrid_non_talking_segment(job, segment)

        self.assertEqual(order, ["facefusion", "audio"])
        self.assertTrue(path.endswith("face_swap_01.mp4"))
        self.assertEqual(segment["faceSwapPath"], "/tmp/job/face_swap_01.mp4")

    def test_standard_identity_mode_skips_facefusion_even_with_uploaded_person(self):
        segment = {
            "index": 1,
            "segmentType": "non_talking",
            "duration": 8,
            "prompt": "preserve motion",
            "sourceSegmentPath": "/tmp/source-segment.mp4",
        }
        job = {
            "identityMode": "standard",
            "outDir": "/tmp/job",
            "productImageUrls": ["https://x/product.png"],
            "sceneImageUrl": "https://x/scene.png",
            "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            "targetFaceReferencePath": "/tmp/target.jpg",
        }
        order = []

        with mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/source.mp4", {"id": "source-temp"})), \
                mock.patch.object(self.client, "lk888_media_task", return_value="https://x/edited.mp4"), \
                mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: path), \
                mock.patch.object(self.client, "_run_facefusion") as facefusion, \
                mock.patch.object(self.client, "_ensure_segment_audio", side_effect=lambda before, after: order.append("audio") or after), \
                mock.patch.object(self.client, "_run_replacement_segment_qc", return_value={"ok": True, "frames": ["a.jpg"]}), \
                mock.patch.object(self.client, "_save_replacement_job"):
            path = self.client._run_hybrid_non_talking_segment(job, segment)

        facefusion.assert_not_called()
        self.assertEqual(order, [])
        self.assertTrue(path.endswith("edited_01.mp4"))
        self.assertEqual(segment["faceSwapPath"], "")

    def test_standard_identity_mode_with_facefusion_flag_runs_facefusion(self):
        segment = {
            "index": 1,
            "segmentType": "non_talking",
            "duration": 8,
            "prompt": "preserve motion",
            "sourceSegmentPath": "/tmp/source-segment.mp4",
        }
        job = {
            "identityMode": "standard",
            "enableFaceFusion": True,
            "outDir": "/tmp/job",
            "productImageUrls": ["https://x/product.png"],
            "sceneImageUrl": "https://x/scene.png",
            "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            "targetFaceReferencePath": "/tmp/target.jpg",
            "facefusionConfig": {"bin": "/tmp/ff", "modelDir": "/tmp/models", "licenseRef": "license", "providers": ["cpu"]},
        }
        order = []

        def facefusion(input_path, output_path, faces, target, config=None):
            order.append("facefusion")
            return output_path

        with mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/source.mp4", {"id": "source-temp"})), \
                mock.patch.object(self.client, "lk888_media_task", return_value="https://x/edited.mp4"), \
                mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: path), \
                mock.patch.object(self.client, "_run_facefusion", side_effect=facefusion), \
                mock.patch.object(self.client, "_ensure_segment_audio", side_effect=lambda before, after: order.append("audio") or after), \
                mock.patch.object(self.client, "_run_replacement_segment_qc", return_value={"ok": True, "frames": ["a.jpg"]}), \
                mock.patch.object(self.client, "_save_replacement_job"):
            path = self.client._run_hybrid_non_talking_segment(job, segment)

        self.assertEqual(order, ["facefusion", "audio"])
        self.assertTrue(path.endswith("face_swap_01.mp4"))
        self.assertEqual(segment["faceSwapPath"], "/tmp/job/face_swap_01.mp4")

    def test_product_image_normalization_is_removed_and_uses_original(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "p1.jpg"
            src.write_bytes(b"fake-image")
            with mock.patch.dict(os.environ, {"VIDEO_REPLACE_PRODUCT_NORMALIZE": "1"}, clear=True), \
                    mock.patch.object(self.client, "upload_asset_url") as upload, \
                    mock.patch.object(self.client, "lk888_image_result") as gen, \
                    mock.patch.object(self.client, "_validate_replacement_product_normalization") as validate:
                path, report = self.client._normalize_replacement_product_image(str(src), td, 1)

            self.assertFalse(report["normalized"])
            self.assertEqual(path, str(src))
            self.assertEqual(report["error"], "product_normalize_removed")
            self.assertEqual(report["fallbackReason"], "using original product image")
            self.assertEqual(report["selectedPath"], str(src))
            upload.assert_not_called()
            gen.assert_not_called()
            validate.assert_not_called()

    def test_product_image_normalization_does_not_call_image_model_on_failure_path(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "p1.jpg"
            src.write_bytes(b"fake-image")
            with mock.patch.dict(os.environ, {"VIDEO_REPLACE_PRODUCT_NORMALIZE": "1"}, clear=True), \
                    mock.patch.object(self.client, "upload_asset_url") as upload, \
                    mock.patch.object(self.client, "lk888_image_result", side_effect=RuntimeError("image_timeout")) as gen:
                path, report = self.client._normalize_replacement_product_image(str(src), td, 1)

            self.assertFalse(report["normalized"])
            self.assertEqual(path, str(src))
            self.assertEqual(report["error"], "product_normalize_removed")
            upload.assert_not_called()
            gen.assert_not_called()

    def test_product_image_normalization_skips_validation_after_removal(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "shower.jpg"
            src.write_bytes(b"source-shower")
            with mock.patch.dict(os.environ, {
                "VIDEO_REPLACE_PRODUCT_NORMALIZE": "1",
                "VIDEO_REPLACE_PRODUCT_NORMALIZE_VALIDATE": "1",
            }, clear=True), \
                    mock.patch.object(self.client, "upload_asset_url") as upload, \
                    mock.patch.object(self.client, "lk888_image_result") as gen, \
                    mock.patch.object(self.client, "_validate_replacement_product_normalization") as validate:
                path, report = self.client._normalize_replacement_product_image(str(src), td, 1)

            self.assertFalse(report["normalized"])
            self.assertEqual(path, str(src))
            self.assertEqual(report["error"], "product_normalize_removed")
            upload.assert_not_called()
            gen.assert_not_called()
            validate.assert_not_called()

    def test_product_image_normalization_respects_env_disable(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "p1.jpg"
            src.write_bytes(b"fake-image")
            with mock.patch.dict(os.environ, {"VIDEO_REPLACE_PRODUCT_NORMALIZE": "0"}, clear=True), \
                    mock.patch.object(self.client, "lk888_image_result") as gen:
                path, report = self.client._normalize_replacement_product_image(str(src), td, 1)

            self.assertFalse(report["normalized"])
            self.assertEqual(path, str(src))
            gen.assert_not_called()

    def test_product_refs_are_processed_with_limited_parallelism_and_ordered_results(self):
        import threading
        import time

        with tempfile.TemporaryDirectory() as td:
            paths = []
            for idx in range(3):
                src = Path(td) / ("p%d.jpg" % (idx + 1))
                src.write_bytes(b"fake-image")
                paths.append(str(src))

            lock = threading.Lock()
            active = {"count": 0, "max": 0}
            two_started = threading.Event()
            progress = []

            def normalize(path, _out_dir, index):
                with lock:
                    active["count"] += 1
                    active["max"] = max(active["max"], active["count"])
                    if active["count"] >= 2:
                        two_started.set()
                if index in (1, 2):
                    two_started.wait(0.25)
                time.sleep(0.02)
                with lock:
                    active["count"] -= 1
                return path + ".norm", {"index": index, "source": os.path.basename(path), "normalized": True}

            def upload(path, _title, _kind):
                with lock:
                    active["count"] += 1
                    active["max"] = max(active["max"], active["count"])
                    if active["count"] >= 2:
                        two_started.set()
                if os.path.basename(path) in ("p1.jpg", "p2.jpg"):
                    two_started.wait(0.25)
                time.sleep(0.02)
                with lock:
                    active["count"] -= 1
                return "https://x/%s" % os.path.basename(path), {"id": os.path.basename(path)}

            with mock.patch.dict(os.environ, {"VIDEO_REPLACE_PRODUCT_PARALLEL": "2"}, clear=True), \
                    mock.patch.object(self.client, "_normalize_replacement_product_image", side_effect=normalize) as normalize_mock, \
                    mock.patch.object(self.client, "upload_asset_url", side_effect=upload):
                urls, reports = self.client._process_replacement_product_refs(paths, td, emit=progress.append)

            self.assertEqual(active["max"], 2)
            self.assertEqual(urls, [
                "https://x/p1.jpg",
                "https://x/p2.jpg",
                "https://x/p3.jpg",
            ])
            self.assertEqual([r["index"] for r in reports], [1, 2, 3])
            self.assertEqual([r["normalized"] for r in reports], [False, False, False])
            normalize_mock.assert_not_called()
            self.assertTrue(any("1/3" in item for item in progress))
            self.assertTrue(any("3/3" in item for item in progress))

    def test_product_ref_processing_uploads_original_without_fallback_progress(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "shower.jpg"
            src.write_bytes(b"source-shower")
            progress = []

            def upload(path, _title, _kind):
                return "https://x/%s" % os.path.basename(path), {}

            with mock.patch.dict(os.environ, {"VIDEO_REPLACE_PRODUCT_PARALLEL": "1"}, clear=True), \
                    mock.patch.object(self.client, "_normalize_replacement_product_image") as normalize, \
                    mock.patch.object(self.client, "upload_asset_url", side_effect=upload):
                urls, reports = self.client._process_replacement_product_refs([str(src)], td, emit=progress.append)

            self.assertEqual(urls, ["https://x/shower.jpg"])
            self.assertEqual(reports[0]["error"], "product_normalize_removed")
            self.assertFalse(any("回退原图" in item for item in progress))
            normalize.assert_not_called()

    def test_replacement_page_emits_product_ref_upload_progress(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn('stage": "product_refs"', src)
        self.assertIn("_upload_refs(lambda message:", src)
        self.assertIn("正在上传产品图", src)

    def test_product_shot_detection_parses_vision_json_and_clamps_best_frame(self):
        with mock.patch.object(
                self.client, "lk888_vision",
                return_value='分析结果 {"visible": true, "bestFrame": 9, "reason": "第二帧产品特写"}') as vision:
            result = self.client._detect_replacement_product_shot(
                {"index": 1}, ["https://x/f1.jpg", "https://x/f2.jpg", "https://x/f3.jpg"],
                ["https://x/product.png"])

        self.assertTrue(result["visible"])
        self.assertEqual(result["bestFrame"], 3)
        self.assertIn("特写", result["reason"])
        media = vision.call_args[0][1]
        self.assertEqual(media[:3], ["https://x/f1.jpg", "https://x/f2.jpg", "https://x/f3.jpg"])
        self.assertEqual(media[-1], "https://x/product.png")

    def test_product_shot_detection_rejects_invalid_response(self):
        with mock.patch.object(self.client, "lk888_vision", return_value="无法判断"):
            with self.assertRaisesRegex(RuntimeError, "product_shot_detect_invalid_response"):
                self.client._detect_replacement_product_shot(
                    {"index": 1}, ["https://x/f1.jpg"], ["https://x/product.png"])

    def _product_anchor_mocks(self, td, visible=True):
        frames = []
        for i in range(3):
            frame = Path(td) / ("frame_%d.jpg" % i)
            frame.write_bytes(b"frame-bytes")
            frames.append(str(frame))
        uploads = []

        def upload(path, name, kind):
            uploads.append((path, name))
            return ("https://x/upload-%d.jpg" % len(uploads), {"id": "m-%d" % len(uploads)})

        vision_reply = '{"visible": %s, "bestFrame": 2, "reason": "ok"}' % ("true" if visible else "false")
        return frames, uploads, upload, vision_reply

    def test_product_anchor_generates_and_injects_anchor_frame(self):
        with tempfile.TemporaryDirectory() as td:
            frames, _uploads, upload, vision_reply = self._product_anchor_mocks(td, visible=True)
            job = {
                "sourceVideoPath": "/tmp/source.mp4",
                "outDir": td,
                "productImageUrls": ["https://x/product.png"],
            }
            segment = {"index": 2, "duration": 8, "segmentType": "non_talking"}
            with mock.patch.dict(os.environ, {"VIDEO_REPLACE_PRODUCT_ANCHOR": "1"}, clear=True), \
                    mock.patch.object(self.client, "_extract_replacement_action_frames", return_value=frames), \
                    mock.patch.object(self.client, "upload_asset_url", side_effect=upload), \
                    mock.patch.object(self.client, "lk888_vision", return_value=vision_reply), \
                    mock.patch.object(self.client, "lk888_image_result", return_value=(b"anchor-bytes" * 8, "https://x/anchor.png")) as gen:
                url = self.client._prepare_replacement_product_anchor(job, segment, td)

            self.assertEqual(url, "https://x/anchor.png")
            self.assertEqual(segment["productAnchorStatus"], "ok")
            self.assertTrue(os.path.isfile(segment["productAnchorFramePath"]))
            self.assertEqual(gen.call_args[1].get("image_urls")[0], "https://x/upload-2.jpg")

            _model, payload = self.client._build_hybrid_video_edit_request(
                dict(job, modelFaceUrl=""), segment, "https://x/source-segment.mp4")
            self.assertIn("https://x/anchor.png", payload["image_urls"])
            self.assertIn("产品锚定帧", payload["prompt"])

    def test_product_anchor_skips_when_product_not_visible(self):
        with tempfile.TemporaryDirectory() as td:
            frames, _uploads, upload, vision_reply = self._product_anchor_mocks(td, visible=False)
            job = {
                "sourceVideoPath": "/tmp/source.mp4",
                "outDir": td,
                "productImageUrls": ["https://x/product.png"],
            }
            segment = {"index": 3, "duration": 8, "segmentType": "non_talking"}
            with mock.patch.dict(os.environ, {"VIDEO_REPLACE_PRODUCT_ANCHOR": "1"}, clear=True), \
                    mock.patch.object(self.client, "_extract_replacement_action_frames", return_value=frames), \
                    mock.patch.object(self.client, "upload_asset_url", side_effect=upload), \
                    mock.patch.object(self.client, "lk888_vision", return_value=vision_reply), \
                    mock.patch.object(self.client, "lk888_image_result") as gen:
                url = self.client._prepare_replacement_product_anchor(job, segment, td)

            self.assertEqual(url, "")
            self.assertEqual(segment["productAnchorStatus"], "skipped_no_product")
            gen.assert_not_called()

            _model, payload = self.client._build_hybrid_video_edit_request(
                dict(job, modelFaceUrl=""), segment, "https://x/source-segment.mp4")
            self.assertNotIn("产品锚定帧", payload["prompt"])

    def test_product_anchor_falls_back_on_image_edit_failure(self):
        with tempfile.TemporaryDirectory() as td:
            frames, _uploads, upload, vision_reply = self._product_anchor_mocks(td, visible=True)
            job = {
                "sourceVideoPath": "/tmp/source.mp4",
                "outDir": td,
                "productImageUrls": ["https://x/product.png"],
            }
            segment = {"index": 4, "duration": 8, "segmentType": "non_talking"}
            with mock.patch.dict(os.environ, {"VIDEO_REPLACE_PRODUCT_ANCHOR": "1"}, clear=True), \
                    mock.patch.object(self.client, "_extract_replacement_action_frames", return_value=frames), \
                    mock.patch.object(self.client, "upload_asset_url", side_effect=upload), \
                    mock.patch.object(self.client, "lk888_vision", return_value=vision_reply), \
                    mock.patch.object(self.client, "lk888_image_result", side_effect=RuntimeError("image_timeout")):
                url = self.client._prepare_replacement_product_anchor(job, segment, td)

            self.assertEqual(url, "")
            self.assertEqual(segment["productAnchorStatus"], "failed")
            self.assertIn("image_timeout", segment["productAnchorWarning"])
            self.assertEqual(segment["productAnchorFrameUrl"], "")

    def test_product_anchor_respects_env_disable(self):
        job = {"productImageUrls": ["https://x/product.png"]}
        segment = {"index": 5, "duration": 8}
        with mock.patch.dict(os.environ, {"VIDEO_REPLACE_PRODUCT_ANCHOR": "0"}, clear=True), \
                mock.patch.object(self.client, "lk888_vision") as vision:
            url = self.client._prepare_replacement_product_anchor(job, segment, "/tmp/job")

        self.assertEqual(url, "")
        self.assertEqual(segment["productAnchorStatus"], "disabled")
        vision.assert_not_called()

    def test_face_similarity_score_parses_json_and_rejects_invalid(self):
        with mock.patch.object(self.client, "lk888_vision", return_value='{"score": 82, "reason": "同一人"}') as vision:
            scored = self.client._score_face_similarity_vision(
                ["https://x/f1.jpg"], ["https://x/face1.png"])

        self.assertEqual(scored["score"], 82.0)
        self.assertEqual(vision.call_args[0][1], ["https://x/f1.jpg", "https://x/face1.png"])

        with mock.patch.object(self.client, "lk888_vision", return_value="看不清"):
            with self.assertRaisesRegex(RuntimeError, "face_similarity_invalid_response"):
                self.client._score_face_similarity_vision(["https://x/f1.jpg"], ["https://x/face1.png"])

    def test_face_similarity_threshold_defaults_and_high_mode_stricter(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.client._replacement_face_similarity_threshold({"identityMode": "standard"}), 70.0)
            self.assertEqual(self.client._replacement_face_similarity_threshold({"identityMode": "high"}), 80.0)
        with mock.patch.dict(os.environ, {"VIDEO_REPLACE_FACE_SIMILARITY_MIN": "65"}, clear=True):
            self.assertEqual(self.client._replacement_face_similarity_threshold({"identityMode": "standard"}), 65.0)
            self.assertEqual(self.client._replacement_face_similarity_threshold({"identityMode": "high"}), 80.0)

    def _face_similarity_job(self, td, faces=2):
        frames = []
        for i in range(3):
            frame = Path(td) / ("qc_%d.jpg" % i)
            frame.write_bytes(b"frame-bytes")
            frames.append(str(frame))
        job = {
            "identityMode": "standard",
            "outDir": td,
            "faceSourceUrls": ["https://x/face%d.png" % i for i in range(faces)],
            "productImageUrls": ["https://x/product.png"],
        }
        return job, frames

    def test_face_similarity_qc_below_threshold_returns_low(self):
        with tempfile.TemporaryDirectory() as td:
            job, frames = self._face_similarity_job(td)
            segment = {"index": 1, "qcFrames": frames}
            with mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/qc.jpg", {"id": "m-qc"})), \
                    mock.patch.object(self.client, "lk888_vision", return_value='{"score": 30, "reason": "五官差异大"}'):
                result = self.client._run_replacement_face_similarity_qc(job, segment)

            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "face_similarity_low")
            self.assertEqual(result["score"], 30.0)
            self.assertEqual(result["threshold"], 70.0)
            self.assertIn("m-qc", job["temporaryMaterialIds"])

    def test_face_similarity_qc_above_threshold_passes(self):
        with tempfile.TemporaryDirectory() as td:
            job, frames = self._face_similarity_job(td)
            segment = {"index": 1, "qcFrames": frames}
            with mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/qc.jpg", {})), \
                    mock.patch.object(self.client, "lk888_vision", return_value='{"score": 91, "reason": "同一人"}'):
                result = self.client._run_replacement_face_similarity_qc(job, segment)

            self.assertTrue(result["ok"])
            self.assertEqual(result["code"], "ok")
            self.assertEqual(result["score"], 91.0)

    def test_face_similarity_qc_defers_on_scoring_failure(self):
        with tempfile.TemporaryDirectory() as td:
            job, frames = self._face_similarity_job(td)
            segment = {"index": 1, "qcFrames": frames}
            with mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/qc.jpg", {})), \
                    mock.patch.object(self.client, "lk888_vision", side_effect=RuntimeError("vision_timeout")), \
                    mock.patch.object(self.client, "_replacement_error_id", return_value="err-face-sim"):
                result = self.client._run_replacement_face_similarity_qc(job, segment)

            self.assertTrue(result["ok"])
            self.assertEqual(result["code"], "face_similarity_deferred")
            self.assertEqual(result["errorId"], "err-face-sim")

    def test_face_similarity_qc_skips_without_person_or_frames(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                self.client._run_replacement_face_similarity_qc(
                    {"noPersonMode": True, "faceSourceUrls": ["https://x/f.png"]}, {"index": 1})["code"],
                "skipped_no_person")
            self.assertEqual(
                self.client._run_replacement_face_similarity_qc(
                    {"faceSimilarityQcEnabled": False, "faceSourceUrls": ["https://x/f.png"]}, {"index": 1})["code"],
                "disabled")
            self.assertEqual(
                self.client._run_replacement_face_similarity_qc(
                    {"faceSourceUrls": ["https://x/f.png"]}, {"index": 1, "qcFrames": []})["code"],
                "skipped_no_frames")
            self.assertEqual(
                self.client._run_replacement_face_similarity_qc({}, {"index": 1, "qcFrames": ["/tmp/x.jpg"]})["code"],
                "skipped_no_reference")

    def test_segment_qc_records_face_similarity_warning_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            job, frames = self._face_similarity_job(td)
            job["sourceVideoPath"] = "/tmp/source.mp4"
            segment = {"index": 1}
            with mock.patch.dict(os.environ, {"VIDEO_REPLACE_VISUAL_QC": "0"}, clear=True), \
                    mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                    mock.patch.object(self.client, "_replacement_audio_qc", return_value={"ok": True}), \
                    mock.patch.object(self.client, "_extract_replacement_qc_frames", return_value=frames), \
                    mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/qc.jpg", {})), \
                    mock.patch.object(self.client, "lk888_vision", return_value='{"score": 30, "reason": "五官差异大"}'):
                qc = self.client._run_replacement_segment_qc(job, segment, "/tmp/edited.mp4")

            self.assertTrue(qc["ok"])
            self.assertEqual(qc["code"], "face_similarity_warning")
            self.assertEqual(segment["faceSimilarity"]["score"], 30.0)
            self.assertEqual(segment["qcWarnings"][0]["code"], "face_similarity_low")

    def test_segment_qc_blocks_low_face_similarity_in_strict_mode(self):
        with tempfile.TemporaryDirectory() as td:
            job, frames = self._face_similarity_job(td)
            job["sourceVideoPath"] = "/tmp/source.mp4"
            job["strictVisualQc"] = True
            segment = {"index": 1}
            with mock.patch.dict(os.environ, {"VIDEO_REPLACE_VISUAL_QC": "0"}, clear=True), \
                    mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                    mock.patch.object(self.client, "_replacement_audio_qc", return_value={"ok": True}), \
                    mock.patch.object(self.client, "_extract_replacement_qc_frames", return_value=frames), \
                    mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/qc.jpg", {})), \
                    mock.patch.object(self.client, "lk888_vision", return_value='{"score": 30, "reason": "五官差异大"}'):
                qc = self.client._run_replacement_segment_qc(job, segment, "/tmp/edited.mp4")

            self.assertFalse(qc["ok"])
            self.assertEqual(qc["code"], "face_similarity_low")

    def test_non_talking_facefusion_failure_falls_back_to_remote_video(self):
        segment = {
            "index": 1,
            "segmentType": "non_talking",
            "duration": 8,
            "prompt": "preserve motion",
            "sourceSegmentPath": "/tmp/source-segment.mp4",
        }
        job = {
            "identityMode": "high",
            "enableFaceFusion": True,
            "outDir": "/tmp/job",
            "productImageUrls": ["https://x/product.png"],
            "sceneImageUrl": "https://x/scene.png",
            "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            "targetFaceReferencePath": "/tmp/target.jpg",
            "facefusionConfig": {"bin": "/tmp/ff", "modelDir": "/tmp/models", "licenseRef": "license", "providers": ["cpu"]},
        }
        order = []

        with mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/source.mp4", {"id": "source-temp"})), \
                mock.patch.object(self.client, "lk888_media_task", return_value="https://x/edited.mp4"), \
                mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: path), \
                mock.patch.object(self.client, "_run_facefusion", side_effect=RuntimeError("facefusion_timeout:33")), \
                mock.patch.object(self.client, "_ensure_segment_audio", side_effect=lambda before, after: order.append((before, after)) or after), \
                mock.patch.object(self.client, "_run_replacement_segment_qc", return_value={"ok": True, "frames": ["a.jpg"]}), \
                mock.patch.object(self.client, "_save_replacement_job"), \
                mock.patch.object(self.client, "_replacement_error_id", return_value="err-facefusion-fallback"):
            path = self.client._run_hybrid_non_talking_segment(job, segment)

        self.assertTrue(path.endswith("edited_01.mp4"))
        self.assertEqual(segment["facefusionStatus"], "fallback")
        self.assertEqual(segment["facefusionErrorId"], "err-facefusion-fallback")
        self.assertEqual(segment["faceSwapPath"], "")
        self.assertEqual(segment["videoPath"], "/tmp/job/edited_01.mp4")
        self.assertEqual(segment["qcWarnings"][0]["code"], "facefusion_failed")
        self.assertEqual(segment["qcWarnings"][0]["severity"], "review_warning")

    def test_facefusion_timeout_is_configurable_and_shorter_than_old_default(self):
        with tempfile.TemporaryDirectory() as td:
            binary = Path(td) / "facefusion"
            model_dir = Path(td) / "models"
            input_video = Path(td) / "input.mp4"
            target_ref = Path(td) / "target.jpg"
            output = Path(td) / "output.mp4"
            faces = [Path(td) / ("face_%d.jpg" % i) for i in range(3)]
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            binary.chmod(0o755)
            model_dir.mkdir()
            input_video.write_bytes(b"video")
            target_ref.write_bytes(b"face")
            for face in faces:
                face.write_bytes(b"face")
            config = {"bin": str(binary), "modelDir": str(model_dir), "licenseRef": "license", "providers": ["cpu"]}

            def timeout_run(args, **kwargs):
                raise subprocess.TimeoutExpired(args, kwargs.get("timeout"))

            with mock.patch.dict(os.environ, {"FACEFUSION_TIMEOUT_SEC": "33"}), \
                    mock.patch.object(self.client.subprocess, "run", side_effect=timeout_run) as run:
                with self.assertRaisesRegex(RuntimeError, "facefusion_timeout:33"):
                    self.client._run_facefusion(
                        str(input_video), str(output), [str(p) for p in faces], str(target_ref), config=config)

        self.assertEqual(run.call_args.kwargs.get("timeout"), 33)

    def test_no_person_segment_skips_facefusion_and_runs_product_qc(self):
        segment = {
            "index": 1,
            "segmentType": "talking",
            "duration": 8,
            "prompt": "preserve product motion",
            "sourceSegmentPath": "/tmp/source-segment.mp4",
        }
        job = {
            "outDir": "/tmp/job",
            "noPersonMode": True,
            "productImageUrls": ["https://x/product.png"],
        }
        order = []

        def upload(path, title, kind):
            order.append("upload")
            return "https://x/source.mp4", {"id": "source-temp"}

        def media(model, payload, exts, progress=None, tries=110):
            order.append("edit")
            return "https://x/edited.mp4"

        def download(url, path):
            order.append("download")
            return path

        with mock.patch.object(self.client, "upload_asset_url", side_effect=upload), \
                mock.patch.object(self.client, "lk888_media_task", side_effect=media), \
                mock.patch.object(self.client, "_wf_download", side_effect=download), \
                mock.patch.object(self.client, "_run_facefusion") as facefusion, \
                mock.patch.object(self.client, "_ensure_segment_audio", side_effect=lambda before, after: order.append("audio") or after), \
                mock.patch.object(self.client, "_run_replacement_segment_qc", return_value={"ok": True, "frames": ["a.jpg"]}), \
                mock.patch.object(self.client, "_save_replacement_job"):
            result = self.client._run_hybrid_replacement_segment(job, segment)

        self.assertTrue(result["ok"])
        self.assertEqual(order, ["upload", "edit", "download"])
        facefusion.assert_not_called()
        self.assertTrue(segment["videoPath"].endswith("edited_01.mp4"))
        self.assertEqual(segment["audioStatus"], "passed")
        self.assertEqual(segment["qcStatus"], "passed")

    def test_review_gate_blocks_unapproved_or_failed_segments(self):
        good = {"status": "done", "audioStatus": "passed", "qcStatus": "passed", "reviewApproved": True}
        self.assertTrue(self.client._replacement_segments_ready_for_final([good]))
        audio_failed = dict(good, audioStatus="failed")
        self.assertTrue(self.client._replacement_segments_ready_for_final([audio_failed]))
        for field, value in (("reviewApproved", False), ("qcStatus", "failed"), ("status", "failed")):
            segment = dict(good)
            segment[field] = value
            with self.subTest(field=field):
                self.assertFalse(self.client._replacement_segments_ready_for_final([segment]))

    def test_tts_talking_segment_edits_video_then_replaces_audio_without_lipsync_model(self):
        with tempfile.TemporaryDirectory() as td:
            base_video = Path(td) / "edited.mp4"
            base_video.write_bytes(b"mp4")
            segment = {
                "index": 1,
                "segmentType": "talking",
                "script": "新的产品口播",
                "prompt": "stable presenter",
                "audioStatus": "pending",
                "qcStatus": "pending",
            }
            job = {"outDir": td, "segments": [segment], "audioMode": "tts", "modelFaceUrl": "https://x/avatar.png"}
            order = []

            def prepare_timing(_job, prepared_segment):
                order.append("prepare_audio")
                prepared_segment["dialogueTimingPrompt"] = "口播时间表"
                return prepared_segment["dialogueTimingPrompt"]

            def edit_video(inner_job, edited_segment):
                order.append("video_edit")
                self.assertEqual(inner_job.get("promptAudioMode"), "tts")
                self.assertEqual(edited_segment.get("dialogueTimingPrompt"), "口播时间表")
                return str(base_video)

            with mock.patch.object(self.client, "_replacement_prepare_dialogue_timing_for_prompt",
                                   side_effect=prepare_timing, create=True) as prepare, \
                    mock.patch.object(self.client, "_run_hybrid_non_talking_segment",
                                      side_effect=edit_video) as edit, \
                    mock.patch.object(self.client, "_replace_replacement_segment_audio_with_tts",
                                      side_effect=lambda _job, _segment, path: order.append("tts_audio") or path) as replace_tts, \
                    mock.patch.object(self.client, "_run_replacement_video_lipsync") as lipsync, \
                    mock.patch.object(self.client, "lk888_digital_human") as human, \
                    mock.patch.object(self.client, "_run_replacement_segment_qc", return_value={
                        "ok": True, "frames": ["first.jpg"], "checks": {"media": "passed", "audio": "passed"},
                    }):
                result = self.client._run_hybrid_replacement_segment(job, segment)

        self.assertTrue(result["ok"])
        self.assertEqual(order, ["prepare_audio", "video_edit", "tts_audio"])
        self.assertEqual(segment["segmentType"], "talking")
        prepare.assert_called_once_with(job, segment)
        edit.assert_called_once()
        replace_tts.assert_called_once_with(job, segment, str(base_video))
        lipsync.assert_not_called()
        human.assert_not_called()
        self.assertEqual(segment["videoPath"], str(base_video))
        self.assertEqual(segment["audioMode"], "tts")
        self.assertEqual(segment["lipSyncStatus"], "skipped_prompt_driven")
    def test_uploaded_talking_segment_replaces_audio_with_clipped_upload_without_lipsync_model(self):
        with tempfile.TemporaryDirectory() as td:
            base_video = Path(td) / "edited.mp4"
            base_video.write_bytes(b"mp4")
            uploaded_audio = Path(td) / "full.mp3"
            uploaded_audio.write_bytes(b"audio")
            segment = {
                "index": 1,
                "segmentType": "talking",
                "script": "新的产品口播",
                "start": 8,
                "end": 16,
                "audioStatus": "pending",
                "qcStatus": "pending",
            }
            job = {
                "outDir": td,
                "segments": [segment],
                "audioMode": "uploaded",
                "replacementAudioPath": str(uploaded_audio),
            }
            order = []

            def prepare_timing(_job, prepared_segment):
                order.append("prepare_audio")
                prepared_segment["dialogueTimingPrompt"] = "上传配音时间表"
                return prepared_segment["dialogueTimingPrompt"]

            def edit_video(inner_job, edited_segment):
                order.append("video_edit")
                self.assertEqual(inner_job.get("promptAudioMode"), "uploaded")
                self.assertEqual(edited_segment.get("dialogueTimingPrompt"), "上传配音时间表")
                return str(base_video)

            with mock.patch.object(self.client, "_replacement_prepare_dialogue_timing_for_prompt",
                                   side_effect=prepare_timing, create=True) as prepare, \
                    mock.patch.object(self.client, "_run_hybrid_non_talking_segment",
                                      side_effect=edit_video) as edit, \
                    mock.patch.object(self.client, "_replace_replacement_segment_audio_with_uploaded",
                                      side_effect=lambda _job, _segment, path: order.append("uploaded_audio") or path) as replace_uploaded, \
                    mock.patch.object(self.client, "_run_replacement_video_lipsync") as lipsync, \
                    mock.patch.object(self.client, "_run_replacement_segment_qc", return_value={
                        "ok": True, "frames": ["first.jpg"], "checks": {"media": "passed", "audio": "passed"},
                    }):
                result = self.client._run_hybrid_replacement_segment(job, segment)

        self.assertTrue(result["ok"])
        self.assertEqual(order, ["prepare_audio", "video_edit", "uploaded_audio"])
        prepare.assert_called_once_with(job, segment)
        edit.assert_called_once()
        replace_uploaded.assert_called_once_with(job, segment, str(base_video))
        lipsync.assert_not_called()
        self.assertEqual(segment["audioMode"], "uploaded")
        self.assertEqual(segment["lipSyncStatus"], "skipped_prompt_driven")
    def test_audio_modes_mark_script_segments_for_lipsync(self):
        scripted = {"script": "新的口播稿"}
        empty = {"script": ""}

        self.assertFalse(self.client._replacement_segment_should_talk(scripted, audio_mode="auto"))
        self.assertFalse(self.client._replacement_segment_should_talk(scripted, audio_mode="source"))
        self.assertTrue(self.client._replacement_segment_should_talk(scripted, audio_mode="tts"))
        self.assertTrue(self.client._replacement_segment_should_talk(scripted, audio_mode="uploaded"))
        self.assertFalse(self.client._replacement_segment_should_talk(empty, audio_mode="uploaded"))

    def test_comic_project_audio_mode_allows_auto_generated_audio(self):
        self.assertEqual(self.client._comic_project_audio_mode_block_reason("auto"), "")
        self.assertEqual(self.client._comic_project_audio_mode_block_reason("source"), "")
        self.assertIn(
            "暂不支持上传完整配音",
            self.client._comic_project_audio_mode_block_reason("uploaded"),
        )

    def test_auto_audio_mode_keeps_generated_video_audio_without_source_mux(self):
        segment = {
            "index": 1,
            "segmentType": "non_talking",
            "duration": 8,
            "sourceSegmentPath": "/tmp/source-segment.mp4",
        }
        job = {
            "outDir": "/tmp/job",
            "audioMode": "auto",
            "principalReplacementMode": "source_video_edit",
            "principalActor": {"status": "detected", "description": "main presenter"},
            "personReferenceUrls": ["https://x/person.jpg"],
        }

        with mock.patch.object(
                self.client, "upload_asset_url",
                return_value=("https://x/source.mp4", {"id": "source-temp"})), \
                mock.patch.object(self.client, "lk888_media_task", return_value="https://x/edited.mp4"), \
                mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: path), \
                mock.patch.object(self.client, "_replace_segment_audio_from_source") as replace_audio, \
                mock.patch.object(self.client, "_ensure_segment_audio") as ensure_audio, \
                mock.patch.object(self.client, "_replace_replacement_segment_audio_with_tts") as replace_tts, \
                mock.patch.object(self.client, "_run_replacement_segment_qc", return_value={
                    "ok": True, "frames": ["a.jpg"], "checks": {"media": "passed", "audio": "passed"},
                }), \
                mock.patch.object(self.client, "_save_replacement_job"):
            path = self.client._run_hybrid_non_talking_segment(job, segment)

        replace_audio.assert_not_called()
        ensure_audio.assert_not_called()
        replace_tts.assert_not_called()
        self.assertEqual(segment["audioMode"], "auto")
        self.assertEqual(segment["audioStatus"], "passed")
        self.assertEqual(path, "/tmp/job/edited_01.mp4")

    def test_uploaded_audio_lipsync_uses_segment_clip(self):
        with tempfile.TemporaryDirectory() as td:
            audio = Path(td) / "full.mp3"
            audio.write_bytes(b"audio")
            segment = {
                "index": 1,
                "segmentType": "talking",
                "script": "新的产品口播",
                "start": 8,
                "end": 16,
                "audioStatus": "pending",
                "qcStatus": "pending",
            }
            job = {
                "outDir": td,
                "segments": [segment],
                "audioMode": "uploaded",
                "modelFaceUrl": "https://x/face.png",
                "replacementAudioPath": str(audio),
                "replacementAudioUrl": "https://x/full.mp3",
            }

            with mock.patch.object(self.client, "_clip_replacement_uploaded_audio_segment",
                                   return_value=str(Path(td) / "clip.mp3")) as clip_audio, \
                    mock.patch.object(self.client, "upload_asset_url",
                                      return_value=("https://x/clip.mp3", {"id": "mat-clip"})) as upload_audio:
                url = self.client._replacement_segment_audio_url_for_lipsync(job, segment)

        self.assertEqual(url, "https://x/clip.mp3")
        clip_audio.assert_called_once()
        upload_audio.assert_called_once()
        self.assertEqual(segment["uploadedAudioSegmentUrl"], "https://x/clip.mp3")

    def test_video_lipsync_requires_configured_existing_video_model(self):
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "edited.mp4"
            video.write_bytes(b"mp4")
            job = {"outDir": td}
            segment = {"index": 1}

            with mock.patch.dict(os.environ, {
                "VIDEO_REPLACE_LIPSYNC_MODEL": "",
                "LK888_VIDEO_LIPSYNC_MODEL": "",
            }, clear=False):
                with self.assertRaisesRegex(RuntimeError, "replacement_lipsync_model_missing"):
                    self.client._run_replacement_video_lipsync(
                        job, segment, str(video), "https://x/audio.mp3")

    def test_replacement_job_is_persisted_atomically(self):
        with tempfile.TemporaryDirectory() as td:
            job = {"id": "job-1", "outDir": td, "status": "awaiting_review", "segments": []}

            path = self.client._save_replacement_job(job)

            self.assertEqual(path, str(Path(td) / "replacement_job.json"))
            self.assertEqual(json.loads(Path(path).read_text(encoding="utf-8"))["status"], "awaiting_review")

    def test_replacement_temp_cleanup_removes_only_expired_jobs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "video_replacements"
            expired = root / "expired"
            recent = root / "recent"
            expired.mkdir(parents=True)
            recent.mkdir()
            (expired / "replacement_job.json").write_text("{}", encoding="utf-8")
            old = 1_700_000_000
            os.utime(expired, (old, old))

            with mock.patch.object(self.client.time, "time", return_value=old + 90000), \
                    mock.patch.dict(os.environ, {"VIDEO_REPLACE_FACE_RETENTION_SEC": "86400"}):
                result = self.client.cleanup_video_replacement_temp_root(td)

            self.assertEqual(result["removed"], 1)
            self.assertFalse(expired.exists())
            self.assertTrue(recent.exists())

    def test_recover_stale_running_replacement_job_marks_partial(self):
        with tempfile.TemporaryDirectory() as td:
            job_dir = Path(td) / "video_replacements" / "job-stale"
            job_dir.mkdir(parents=True)
            job = {
                "id": "job-stale",
                "outDir": str(job_dir),
                "status": "running",
                "updatedAt": 1000.0,
                "segments": [
                    {"index": 1, "status": "done", "videoPath": "done.mp4", "qcStatus": "passed"},
                    {"index": 2, "status": "video_edit", "qcStatus": "pending", "errorId": ""},
                ],
            }
            (job_dir / "replacement_job.json").write_text(json.dumps(job), encoding="utf-8")

            result = self.client.recover_stale_video_replacement_jobs(td, now=2000.0)

            self.assertEqual(result["recovered"], 1)
            saved = json.loads((job_dir / "replacement_job.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "partial")
            self.assertEqual(saved["recoveryReason"], "stale_running_recovered")
            self.assertEqual(saved["segments"][0]["status"], "done")
            self.assertEqual(saved["segments"][1]["status"], "failed")
            self.assertEqual(saved["segments"][1]["error"], "stale_running_recovered")
            self.assertTrue(saved["segments"][1]["errorId"].startswith("err-"))

    def test_recover_stale_running_replacement_job_marks_failed_without_done_segments(self):
        with tempfile.TemporaryDirectory() as td:
            job_dir = Path(td) / "video_replacements" / "job-failed"
            job_dir.mkdir(parents=True)
            job = {
                "id": "job-failed",
                "outDir": str(job_dir),
                "status": "running",
                "segments": [
                    {"index": 1, "status": "downloading", "qcStatus": "pending"},
                    {"index": 2, "status": "pending", "qcStatus": "pending"},
                ],
            }
            (job_dir / "replacement_job.json").write_text(json.dumps(job), encoding="utf-8")

            result = self.client.recover_stale_video_replacement_jobs(td, now=2000.0)

            self.assertEqual(result["recovered"], 1)
            saved = json.loads((job_dir / "replacement_job.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "failed")
            self.assertEqual(saved["segments"][0]["status"], "failed")
            self.assertEqual(saved["segments"][1]["status"], "pending")

    def test_prepare_replacement_segment_for_retry_demotes_legacy_false_blocks(self):
        segment = {
            "index": 4,
            "status": "failed",
            "audioStatus": "failed",
            "qcStatus": "failed",
            "error": "replacement_qc_failed:role_mismatch",
            "errorId": "err-old-role",
            "blockedReason": "visual_drift_retry_exhausted",
            "qcWarnings": [
                {"code": "role_mismatch", "severity": "blocking", "reason": "旧规则误拦截"},
                {"code": "structure_mismatch", "severity": "blocking", "reason": "旧规则误拦截"},
            ],
        }

        summary = self.client._prepare_replacement_segment_for_retry(segment)

        self.assertTrue(summary["retryable"])
        self.assertEqual(summary["demotedCodes"], ["role_mismatch", "structure_mismatch"])
        self.assertEqual(segment["status"], "pending")
        self.assertEqual(segment["audioStatus"], "pending")
        self.assertEqual(segment["qcStatus"], "pending")
        self.assertEqual(segment["error"], "")
        self.assertEqual(segment["errorId"], "")
        self.assertEqual(segment["blockedReason"], "")
        self.assertEqual(segment["retryHistory"][0]["errorId"], "err-old-role")
        self.assertEqual([w["severity"] for w in segment["qcWarnings"]], ["review_warning", "review_warning"])

    def test_prepare_replacement_segment_for_retry_retains_hard_drift_history(self):
        segment = {
            "index": 2,
            "status": "failed",
            "audioStatus": "passed",
            "qcStatus": "failed",
            "error": "replacement_qc_failed:visual_drift_retry_exhausted",
            "errorId": "err-hard-drift",
            "blockedReason": "visual_drift_retry_exhausted",
            "qcWarnings": [
                {"code": "visual_drift_retry_exhausted", "severity": "blocking", "reason": "仍跑偏"},
            ],
        }

        summary = self.client._prepare_replacement_segment_for_retry(segment)

        self.assertTrue(summary["retryable"])
        self.assertEqual(summary["demotedCodes"], [])
        self.assertEqual(segment["status"], "pending")
        self.assertEqual(segment["error"], "")
        self.assertEqual(segment["errorId"], "")
        self.assertEqual(segment["retryHistory"][0]["blockedReason"], "visual_drift_retry_exhausted")
        self.assertEqual(segment["retryHistory"][0]["qcWarnings"][0]["severity"], "blocking")

    def test_prepare_manual_defect_regeneration_adds_prompt_guard(self):
        segment = {
            "index": 3,
            "status": "done",
            "audioStatus": "passed",
            "qcStatus": "passed",
            "videoPath": "/tmp/old.mp4",
            "editedVideoPath": "/tmp/old-edited.mp4",
            "faceSwapPath": "/tmp/old-face.mp4",
            "prompt": "保留原片动作",
        }

        summary = self.client._prepare_replacement_segment_for_manual_regeneration(
            segment, "上一版右手手指变形，产品 Logo 变糊")
        prompt = self.client._build_hybrid_video_edit_request(
            {
                "productImageUrls": ["https://cdn.example.com/product.png"],
                "modelFaceUrl": "https://cdn.example.com/person.png",
            },
            segment,
            "https://cdn.example.com/source.mp4",
        )[1]["prompt"]

        self.assertTrue(summary["retryable"])
        self.assertEqual(segment["status"], "pending")
        self.assertEqual(segment["audioStatus"], "pending")
        self.assertEqual(segment["qcStatus"], "pending")
        self.assertEqual(segment["videoPath"], "")
        self.assertEqual(segment["manualDefectNote"], "上一版右手手指变形，产品 Logo 变糊")
        self.assertEqual(segment["retryHistory"][0]["videoPath"], "/tmp/old.mp4")
        self.assertIn("手动瑕疵重生", prompt)
        self.assertIn("右手手指变形", prompt)
        self.assertIn("不能再次出现", prompt)

    def test_subtitle_preflight_flags_suspicious_or_unreviewed_text(self):
        reviewed = {"index": 1, "script": "给你详细地介绍一下", "scriptReviewed": True}
        suspicious = {"index": 2, "script": "给你详经地介绍一下", "scriptReviewed": True}
        mojibake = {"index": 3, "script": "鎶婁骇品介绍清楚", "scriptReviewed": True}
        unreviewed = {"index": 4, "script": "这是一段原始识别字幕"}

        issues = self.client._replacement_subtitle_text_issues([reviewed, suspicious, mojibake, unreviewed])

        self.assertEqual([item["index"] for item in issues], [2, 3, 4])
        self.assertEqual(issues[0]["code"], "suspect_subtitle_word")
        self.assertEqual(issues[1]["code"], "subtitle_mojibake")
        self.assertEqual(issues[2]["code"], "subtitle_not_reviewed")

    def test_subtitle_burn_uses_fixed_font_directory_when_available(self):
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "raw.mp4"
            subtitle = Path(td) / "raw.ass"
            output = Path(td) / "raw_subtitled.mp4"
            font = Path(td) / "msyh.ttc"
            video.write_bytes(b"video")
            font.write_bytes(b"font")

            def fake_run(cmd, **_kwargs):
                output.write_bytes(b"subtitled-video" * 200)
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch.object(self.client, "_write_replacement_subtitle_ass", return_value={
                "ok": True, "path": str(subtitle), "events": [{"text": "中文"}],
            }), mock.patch.object(self.client.subprocess, "run", side_effect=fake_run) as run, \
                    mock.patch.dict(os.environ, {"VIDEO_REPLACE_SUBTITLE_FONT_FILE": str(font)}, clear=False):
                result = self.client._burn_replacement_subtitles({"segments": [{"script": "中文"}]}, str(video))

        vf = run.call_args.args[0][run.call_args.args[0].index("-vf") + 1]
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "burned")
        self.assertIn("fontsdir", vf)
        self.assertIn(str(font.parent).replace("\\", "/")[0], vf)

    def test_retry_normalization_merges_legacy_too_short_tail_into_previous_segment(self):
        job = {
            "id": "job-legacy-short-tail",
            "segments": [
                {"index": 1, "start": 0.0, "end": 8.0, "duration": 8.0, "status": "done", "videoPath": "seg1.mp4"},
                {"index": 2, "start": 8.0, "end": 16.0, "duration": 8.0, "status": "done", "videoPath": "seg2.mp4"},
                {
                    "index": 3,
                    "start": 16.0,
                    "end": 17.47,
                    "duration": 1.47,
                    "status": "failed",
                    "error": "principal_video_edit_failed",
                    "errorId": "err-short-tail",
                },
            ],
        }
        failed = [job["segments"][2]]

        retry_segments, summary = self.client._normalize_replacement_retry_segments(job, failed)

        self.assertEqual(len(job["segments"]), 2)
        self.assertEqual(job["segments"][1]["index"], 2)
        self.assertEqual(job["segments"][1]["start"], 8.0)
        self.assertEqual(job["segments"][1]["end"], 17.47)
        self.assertGreaterEqual(job["segments"][1]["duration"], 3.0)
        self.assertEqual(job["segments"][1]["status"], "failed")
        self.assertEqual(retry_segments, [job["segments"][1]])
        self.assertEqual(summary["mergedShortTailSegments"], [{"fromIndex": 3, "intoIndex": 2}])
        self.assertEqual(job["segments"][1]["retryHistory"][0]["errorId"], "err-short-tail")

    def test_visual_qc_blocks_product_mismatch(self):
        job = {
            "productImageUrls": ["https://x/product.png"],
            "modelFaceUrl": "https://x/face.png",
            "sceneImageUrl": "https://x/scene.png",
            "temporaryMaterialIds": [],
        }
        segment = {"index": 1}
        response = (
            '{"faceMatch":true,"productMatch":false,"logoTextReadable":false,'
            '"sceneMatch":true,"reason":"包装和 logo 不一致"}'
        )
        with mock.patch.object(self.client, "upload_asset_url", return_value=(
                "https://x/result.mp4", {"data": {"id": "temp-video", "url": "https://x/result.mp4"}}
        )), mock.patch.object(self.client, "lk888_vision", return_value=response):
            result = self.client._run_replacement_visual_qc(job, segment, "/tmp/result.mp4")

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "product_mismatch")
        self.assertEqual(job["temporaryMaterialIds"], ["temp-video"])

    def test_visual_qc_blocks_severe_topic_drift_in_all_identity_modes(self):
        response = (
            '{"sourceProductVisible":true,"faceMatch":true,"productMatch":true,'
            '"logoTextReadable":true,"sceneMatch":true,'
            '"topicMatch":false,"roleMatch":false,"structureMatch":false,'
            '"severeDrift":true,"reason":"汽车销售视频变成美妆主播化妆品近景"}'
        )
        for mode in ("fast", "standard", "high"):
            with self.subTest(mode=mode):
                job = {
                    "identityMode": mode,
                    "productImageUrls": ["https://x/car.png"],
                    "modelFaceUrl": "https://x/face.png",
                    "sceneImageUrl": "https://x/showroom.png",
                    "temporaryMaterialIds": [],
                }
                segment = {"index": 1}
                with mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/result.mp4", {})), \
                        mock.patch.object(self.client, "lk888_vision", return_value=response):
                    result = self.client._run_replacement_visual_qc(job, segment, "/tmp/result.mp4")

                self.assertFalse(result["ok"])
                self.assertEqual(result["code"], "visual_drift_blocked")
                self.assertTrue(result["visualDriftQc"]["severeDrift"])

    def test_visual_qc_keeps_regular_face_mismatch_as_review_warning_policy(self):
        job = {
            "identityMode": "standard",
            "productImageUrls": ["https://x/product.png"],
            "modelFaceUrl": "https://x/face.png",
            "temporaryMaterialIds": [],
        }
        segment = {"index": 1}
        response = (
            '{"sourceProductVisible":true,"faceMatch":false,"productMatch":true,'
            '"logoTextReadable":true,"sceneMatch":true,'
            '"topicMatch":true,"roleMatch":true,"structureMatch":true,'
            '"severeDrift":false,"reason":"脸不够像"}'
        )

        with mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/result.mp4", {})), \
                mock.patch.object(self.client, "lk888_vision", return_value=response), \
                mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "_replacement_audio_qc", return_value={"ok": True}), \
                mock.patch.object(self.client, "_extract_replacement_qc_frames", return_value=["a.jpg", "b.jpg", "c.jpg"]):
            result = self.client._run_replacement_segment_qc(job, segment, "/tmp/result.mp4")

        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "visual_qc_warning")
        self.assertEqual(segment["qcWarnings"][0]["severity"], "review_warning")

    def test_visual_qc_no_person_mode_ignores_face_mismatch(self):
        job = {
            "noPersonMode": True,
            "productImageUrls": ["https://x/product.png"],
            "temporaryMaterialIds": [],
        }
        segment = {"index": 1}
        response = (
            '{"faceMatch":false,"productMatch":true,"logoTextReadable":true,'
            '"sceneMatch":false,"reason":"没有人物，产品一致"}'
        )
        with mock.patch.object(self.client, "upload_asset_url", return_value=(
                "https://x/result.mp4", {"data": {"id": "temp-video", "url": "https://x/result.mp4"}}
        )), mock.patch.object(self.client, "lk888_vision", return_value=response):
            result = self.client._run_replacement_visual_qc(job, segment, "/tmp/result.mp4")

        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "ok")
        self.assertEqual(result["checks"]["face"], "skipped")
        self.assertEqual(result["checks"]["scene"], "skipped")

    def test_visual_qc_skips_product_when_source_segment_has_no_product(self):
        job = {
            "productImageUrls": ["https://x/product.png"],
            "modelFaceUrl": "https://x/face.png",
            "temporaryMaterialIds": [],
        }
        segment = {"index": 1, "sourceSegmentUrl": "https://x/source.mp4"}
        response = (
            '{"sourceProductVisible":false,"faceMatch":true,'
            '"productMatch":false,"logoTextReadable":false,'
            '"sceneMatch":true,"reason":"原片这一段没有车，生成结果也没有车"}'
        )
        with mock.patch.object(self.client, "upload_asset_url", return_value=(
                "https://x/result.mp4", {"data": {"id": "temp-video", "url": "https://x/result.mp4"}}
        )), mock.patch.object(self.client, "lk888_vision", return_value=response):
            result = self.client._run_replacement_visual_qc(job, segment, "/tmp/result.mp4")

        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "ok")
        self.assertFalse(result["sourceProductVisible"])
        self.assertEqual(result["checks"]["product"], "skipped_source_absent")
        self.assertEqual(result["checks"]["logoText"], "skipped_source_absent")

    def test_visual_qc_blocks_scene_reference_mismatch_when_scene_uploaded(self):
        job = {
            "productImageUrls": ["https://x/car.png"],
            "modelFaceUrl": "https://x/face.png",
            "sceneImageUrl": "https://x/showroom.png",
            "scenePrompt": "bright indoor showroom",
            "temporaryMaterialIds": [],
        }
        segment = {"index": 2, "sourceSegmentUrl": "https://x/source-car-interior.mp4"}
        response = (
            '{"sourceProductVisible":true,"faceMatch":true,"productMatch":true,'
            '"logoTextReadable":true,"sceneMatch":false,'
            '"topicMatch":true,"roleMatch":true,"structureMatch":true,'
            '"severeDrift":false,"reason":"原片为车内细节，场景图为展厅，但仍是汽车内容"}'
        )
        with mock.patch.object(self.client, "upload_asset_url", return_value=(
                "https://x/result.mp4", {"data": {"id": "temp-video", "url": "https://x/result.mp4"}}
        )), mock.patch.object(self.client, "lk888_vision", return_value=response):
            result = self.client._run_replacement_visual_qc(job, segment, "/tmp/result.mp4")

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "scene_mismatch")
        self.assertEqual(result["checks"]["scene"], "failed")

    def test_visual_qc_timeout_defers_to_manual_review_without_failing_segment(self):
        job = {
            "outDir": "/tmp/job",
            "productImageUrls": ["https://x/product.png"],
            "modelFaceUrl": "https://x/face.png",
            "temporaryMaterialIds": [],
        }
        segment = {"index": 1}

        with mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "_replacement_audio_qc", return_value={"ok": True}), \
                mock.patch.object(self.client, "_extract_replacement_qc_frames",
                                  return_value=["first.jpg", "middle.jpg", "last.jpg"]), \
                mock.patch.object(self.client, "_run_replacement_visual_qc",
                                  side_effect=self.client.requests.exceptions.ReadTimeout("timeout")), \
                mock.patch.object(self.client, "_replacement_error_id", return_value="err-qc-timeout"):
            result = self.client._run_replacement_segment_qc(job, segment, "/tmp/result.mp4")

        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "visual_qc_deferred")
        self.assertEqual(result["checks"]["face"], "awaiting_review")
        self.assertEqual(result["visual"]["errorId"], "err-qc-timeout")

    def test_visual_qc_mismatch_warns_without_failing_segment_by_default(self):
        job = {
            "outDir": "/tmp/job",
            "productImageUrls": ["https://x/product.png"],
            "modelFaceUrl": "https://x/face.png",
        }
        segment = {"index": 1}

        with mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "_replacement_audio_qc", return_value={"ok": True}), \
                mock.patch.object(self.client, "_extract_replacement_qc_frames",
                                  return_value=["first.jpg", "middle.jpg", "last.jpg"]), \
                mock.patch.object(self.client, "_run_replacement_visual_qc", return_value={
                    "ok": False,
                    "code": "product_mismatch",
                    "reason": "产品不一致",
                    "checks": {"face": "passed", "product": "failed", "logoText": "failed", "scene": "skipped"},
                }):
            result = self.client._run_replacement_segment_qc(job, segment, "/tmp/result.mp4")

        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "visual_qc_warning")
        self.assertEqual(result["warnings"][0]["code"], "product_mismatch")
        self.assertEqual(result["warnings"][0]["severity"], "review_warning")
        self.assertEqual(segment["qcWarnings"][0]["code"], "product_mismatch")

    def test_visual_qc_role_mismatch_warns_when_topic_is_preserved(self):
        job = {
            "outDir": "/tmp/job",
            "productImageUrls": ["https://x/product.png"],
            "modelFaceUrl": "https://x/face.png",
        }
        segment = {"index": 1}

        with mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "_replacement_audio_qc", return_value={"ok": True}), \
                mock.patch.object(self.client, "_extract_replacement_qc_frames",
                                  return_value=["first.jpg", "middle.jpg", "last.jpg"]), \
                mock.patch.object(self.client, "_run_replacement_visual_qc", return_value={
                    "ok": False,
                    "code": "role_mismatch",
                    "reason": "原片无人物产品特写段，生成结果未出现人物但仍是汽车内容",
                    "checks": {"face": "failed", "product": "passed", "logoText": "passed", "scene": "passed"},
                    "visualDriftQc": {
                        "topicMatch": True,
                        "roleMatch": False,
                        "structureMatch": True,
                        "severeDrift": False,
                        "reason": "未发生严重跑题",
                    },
                }):
            result = self.client._run_replacement_segment_qc(job, segment, "/tmp/result.mp4")

        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "visual_qc_warning")
        self.assertEqual(segment["qcWarnings"][0]["code"], "role_mismatch")
        self.assertEqual(segment["qcWarnings"][0]["severity"], "review_warning")

    def test_visual_qc_structure_mismatch_warns_when_topic_is_preserved(self):
        job = {
            "outDir": "/tmp/job",
            "productImageUrls": ["https://x/car.png"],
            "modelFaceUrl": "https://x/face.png",
        }
        segment = {"index": 4}

        with mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "_replacement_audio_qc", return_value={"ok": True}), \
                mock.patch.object(self.client, "_extract_replacement_qc_frames",
                                  return_value=["first.jpg", "middle.jpg", "last.jpg"]), \
                mock.patch.object(self.client, "_run_replacement_visual_qc", return_value={
                    "ok": False,
                    "code": "structure_mismatch",
                    "reason": "汽车产品特写镜头结构变化，但仍展示汽车产品，未发生严重跑题",
                    "checks": {"face": "passed", "product": "failed", "logoText": "failed", "scene": "passed"},
                    "visualDriftQc": {
                        "topicMatch": True,
                        "roleMatch": True,
                        "structureMatch": False,
                        "severeDrift": False,
                        "reason": "未发生严重跑题",
                    },
                }):
            result = self.client._run_replacement_segment_qc(job, segment, "/tmp/result.mp4")

        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "visual_qc_warning")
        self.assertEqual(segment["qcWarnings"][0]["code"], "structure_mismatch")
        self.assertEqual(segment["qcWarnings"][0]["severity"], "review_warning")

    def test_visual_qc_can_be_strict_by_env(self):
        job = {
            "outDir": "/tmp/job",
            "productImageUrls": ["https://x/product.png"],
            "modelFaceUrl": "https://x/face.png",
        }
        segment = {"index": 1}

        with mock.patch.dict(os.environ, {"VIDEO_REPLACE_STRICT_VISUAL_QC": "1"}), \
                mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "_replacement_audio_qc", return_value={"ok": True}), \
                mock.patch.object(self.client, "_extract_replacement_qc_frames",
                                  return_value=["first.jpg", "middle.jpg", "last.jpg"]), \
                mock.patch.object(self.client, "_run_replacement_visual_qc", return_value={
                    "ok": False,
                    "code": "face_mismatch",
                    "reason": "人物不一致",
                    "checks": {"face": "failed", "product": "passed", "logoText": "passed", "scene": "skipped"},
                }):
            result = self.client._run_replacement_segment_qc(job, segment, "/tmp/result.mp4")

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "face_mismatch")

    def test_delete_replacement_segment_reindexes_pending_segments(self):
        job = {
            "segments": [
                {"index": 1, "status": "pending", "start": 0, "end": 8, "duration": 8},
                {"index": 2, "status": "pending", "start": 8, "end": 16, "duration": 8},
                {"index": 3, "status": "pending", "start": 16, "end": 24, "duration": 8},
            ],
        }

        removed = self.client._delete_replacement_segment(job, 2)

        self.assertTrue(removed)
        self.assertEqual([item["index"] for item in job["segments"]], [1, 2])
        self.assertEqual([item["start"] for item in job["segments"]], [0, 8])
        self.assertEqual([item["end"] for item in job["segments"]], [8, 16])
        self.assertEqual([item["duration"] for item in job["segments"]], [8, 8])

    def test_delete_replacement_segment_preserves_current_edited_scripts(self):
        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._job = {
            "segments": [
                {"index": 1, "status": "pending", "start": 0, "end": 8, "script": "old first", "scriptReviewed": True},
                {"index": 2, "status": "pending", "start": 8, "end": 16, "script": "old second"},
                {"index": 3, "status": "pending", "start": 16, "end": 24, "script": "old third"},
            ],
        }
        page.table = _FakeTable()
        page.table.rowCount = lambda: 3
        edited = ["edited first", "edited second", "edited third"]
        page._segment_script_value = lambda row: edited[row]

        page._sync_segment_scripts_from_table()
        removed = self.client._delete_replacement_segment(page._job, 2)

        self.assertTrue(removed)
        self.assertEqual([item["script"] for item in page._job["segments"]], ["edited first", "edited third"])
        self.assertIs(page._job["segments"][0].get("scriptReviewed"), False)

    def test_delete_replacement_segment_refuses_started_segments(self):
        job = {"segments": [{"index": 1, "status": "done"}]}

        removed = self.client._delete_replacement_segment(job, 1)

        self.assertFalse(removed)
        self.assertEqual(len(job["segments"]), 1)

    def test_replacement_transcription_issue_text_warns_about_failed_speech(self):
        analysis = {
            "transcript": {
                "status": "failed",
                "text": "",
                "segments": [],
                "failedRanges": [{"start": 0.0, "end": 17.77, "code": "remote_timeout"}],
            }
        }

        text = self.client._replacement_transcription_issue_text(analysis)

        self.assertIn("口播识别失败", text)
        self.assertIn("超时", text)
        self.assertIn("重试口播", text)

    def test_replacement_transcription_retry_updates_source_and_job_analysis(self):
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "video.mp4"
            video.write_bytes(b"fake-video")
            page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
            page._busy = False
            page._source = {
                "sourceVideoPath": str(video),
                "breakdownAnalysis": {
                    "meta": {"duration": 17.77},
                    "transcript": {
                        "status": "failed",
                        "retryCount": 0,
                        "text": "",
                        "segments": [],
                        "failedRanges": [{"start": 0.0, "end": 17.77, "code": "remote_timeout"}],
                        "errors": [{"start": 0.0, "end": 17.77, "code": "remote_timeout"}],
                    },
                },
            }
            page._job = {
                "id": "job-retry-transcript",
                "outDir": td,
                "breakdownAnalysis": dict(page._source["breakdownAnalysis"]),
                "segments": [{"index": 1, "script": ""}],
            }
            page.status = _FakeWidget()
            page.b_retry_transcript = _FakeWidget()
            page.b_plan = _FakeWidget()
            page.refresh_segments = mock.Mock()
            page._set_generation_feedback = mock.Mock()
            saved = []
            emitted = []
            bridge = types.SimpleNamespace(payload=types.SimpleNamespace(
                emit=lambda tag, payload: emitted.append((tag, payload))
            ))
            retried = {
                "status": "ok",
                "chunks": [{
                    "start": 0.0,
                    "end": 17.77,
                    "language": "zh-CN",
                    "segments": [{"startSec": 0.0, "endSec": 2.0, "text": "重试后识别出的口播"}],
                }],
                "failedRanges": [],
                "errors": [],
            }

            with mock.patch.object(self.client, "run_bg", side_effect=lambda fn: fn()), \
                    mock.patch.object(self.client, "data_dir", return_value=td), \
                    mock.patch.object(self.client, "write_video_breakdown_job_owner", create=True), \
                    mock.patch.object(self.client, "_transcribe_breakdown_audio", return_value=retried), \
                    mock.patch.object(self.client, "_generate_video_breakdown_report",
                                      return_value=("## updated", "分析完成")), \
                    mock.patch.object(self.client, "_save_replacement_job",
                                      side_effect=lambda job: saved.append(dict(job))), \
                    mock.patch.object(self.client, "BRIDGE", bridge):
                page.retry_source_transcription()
                done = [payload for tag, payload in emitted if tag == "video_replace_transcription_retry_done"][-1]
                page._on("video_replace_transcription_retry_done", done)

            transcript = page._source["breakdownAnalysis"]["transcript"]
            self.assertEqual(transcript["status"], "ok")
            self.assertEqual(transcript["failedRanges"], [])
            self.assertIn("重试后识别出的口播", transcript["text"])
            self.assertIn("重试后识别出的口播", page._job["breakdownAnalysis"]["transcript"]["text"])
            self.assertEqual(saved[-1]["breakdownAnalysis"]["transcript"]["status"], "ok")
            self.assertIn("可以重新生成替换方案", page.status.text())

    def test_replacement_error_display_uses_chinese_without_mutating_raw_code(self):
        segment = {
            "errorId": "err-face",
            "error": "replacement_qc_failed:face_mismatch",
        }

        display = self.client._replacement_segment_display_error(segment)

        self.assertIn("质检失败", display)
        self.assertIn("人脸", display)
        self.assertNotIn("错误编号", display)
        self.assertNotIn("err-face", display)
        self.assertNotIn("replacement_qc_failed", display)
        self.assertNotIn("face_mismatch", display)
        self.assertEqual(segment["error"], "replacement_qc_failed:face_mismatch")

    def test_replacement_error_display_localizes_gateway_image_errors(self):
        display = self.client._localize_replacement_display_text(
            "替换生成失败（错误编号 err-504）:图片生成 504: <html><h1>504 Gateway Time-out</h1>"
        )

        self.assertIn("图片生成服务暂时不可用或超时", display)
        self.assertNotIn("错误编号", display)
        self.assertNotIn("err-504", display)
        self.assertNotIn("Gateway", display)
        self.assertNotIn("<html>", display)

    def test_replacement_error_display_localizes_remote_media_required(self):
        display = self.client._localize_replacement_display_text(
            "错误编号 err-6077c2486cac4a3b; video_replace_remote_media_required"
        )

        self.assertIn("源片段地址不是公网可访问地址", display)
        self.assertNotIn("错误编号", display)
        self.assertNotIn("err-6077c2486cac4a3b", display)
        self.assertNotIn("video_replace_remote_media_required", display)

    def test_replacement_error_display_localizes_facefusion_timeout_and_green_check(self):
        timeout_display = self.client._localize_replacement_display_text(
            "错误编号 err-face; facefusion_timeout:420"
        )
        green_display = self.client._localize_replacement_display_text(
            "错误编号 err-green; happyhorse-video-edit 生成失败:status=错误; message=图像（输入）绿网检查失败"
        )

        self.assertIn("本地换脸增强超时", timeout_display)
        self.assertIn("已回退远程同款结果", timeout_display)
        self.assertNotIn("错误编号", timeout_display)
        self.assertNotIn("err-face", timeout_display)
        self.assertNotIn("facefusion_timeout", timeout_display)
        self.assertIn("上游内容审核未通过", green_display)
        self.assertNotIn("错误编号", green_display)
        self.assertNotIn("err-green", green_display)
        self.assertNotIn("绿网", green_display)

    def test_replacement_error_display_localizes_remote_read_timeout(self):
        raw = (
            "替换生成失败（错误编号 err-timeout）:"
            "HTTPConnectionPool(host='120.26.194.174', port=80): "
            "Read timed out. (read timeout=60)"
        )

        display = self.client._localize_replacement_display_text(raw)

        self.assertEqual(
            "远程服务响应超时，本次生成没有在限定时间内返回。"
            "请稍后重试；如果连续出现，请重启本地客户端后再试。",
            display,
        )
        self.assertNotIn("HTTPConnectionPool", display)
        self.assertNotIn("Read timed out", display)
        self.assertNotIn("错误编号", display)
        self.assertNotIn("err-timeout", display)

    def test_replacement_error_display_localizes_remote_connection_failure(self):
        raw = (
            "错误编号 err-connect；ConnectionError: "
            "HTTPConnectionPool(host='120.26.194.174', port=80): "
            "Max retries exceeded with url: /api/v1/comic-drama/projects "
            "(Caused by NewConnectionError: Failed to establish a new connection)"
        )

        display = self.client._localize_replacement_display_text(raw)

        self.assertEqual(
            "无法连接远程服务，请检查网络状态或本地客户端是否为最新版本。",
            display,
        )
        self.assertNotIn("ConnectionError", display)
        self.assertNotIn("HTTPConnectionPool", display)
        self.assertNotIn("错误编号", display)

    def test_replacement_error_display_localizes_remote_file_descriptor_exhaustion(self):
        raw = (
            "comic_api_http_502:{'detail': "
            "\"平台服务调用失败：URLError(OSError(24, 'Too many open files'))\"}"
        )

        display = self.client._localize_replacement_display_text(raw)

        self.assertEqual(
            "远程漫剧服务资源句柄耗尽，视频生成暂时不可用。请稍后重试；如果连续出现，需要重启远程漫剧服务并检查句柄泄漏。",
            display,
        )
        self.assertNotIn("URLError", display)
        self.assertNotIn("Too many open files", display)
        self.assertNotIn("OSError", display)
        self.assertNotIn("err-connect", display)

    def test_replacement_error_display_localizes_invalid_comic_video_duration(self):
        display = self.client._localize_replacement_display_text(
            "替换生成失败（错误编号 err-video）:comic_segment_invalid:media_invalid_duration"
        )

        self.assertEqual("远程返回的生成片段不是有效视频，请单段重试。", display)
        self.assertNotIn("comic_segment_invalid", display)
        self.assertNotIn("media_invalid_duration", display)
        self.assertNotIn("错误编号", display)

    def test_replacement_error_display_keeps_remote_message_without_error_id(self):
        display = self.client._localize_replacement_display_text(
            "错误编号 err-real-person；kwvideo-v2-quannengcankao 生成失败:status=错误; "
            "message=请求失败，因为输入视频可能包含真人。请求id："
        )

        self.assertIn("请求失败，因为输入视频可能包含真人", display)
        self.assertNotIn("错误编号", display)
        self.assertNotIn("err-real-person", display)
        self.assertNotIn("请根据错误编号查看日志", display)

    def test_replacement_error_display_localizes_policy_violation(self):
        display = self.client._localize_replacement_display_text(
            "错误编号 err-policy；comic_task_failed:ark 400 Bad Request: "
            "{\"error\":{\"code\":\"InputImageSensitiveContentDetected.PolicyViolation\","
            "\"message\":\"The request failed because the input image 'content[6]' "
            "may be related to copyright restrictions.\"}}"
        )

        self.assertIn("上游模型拒绝了输入参考图", display)
        self.assertIn("版权", display)
        self.assertIn("切换备用模型", display)
        self.assertNotIn("错误编号", display)
        self.assertNotIn("err-policy", display)
        self.assertNotIn("InputImageSensitiveContentDetected", display)

    def test_replacement_segment_display_prefers_error_content_without_error_id(self):
        segment = {
            "status": "failed",
            "errorId": "err-segment",
            "error": "comic_storyboard_id_missing:segment_1",
        }

        display = self.client._replacement_segment_display_error(segment)

        self.assertIn("comic_storyboard_id_missing:segment_1", display)
        self.assertNotIn("错误编号", display)
        self.assertNotIn("err-segment", display)

    def test_replacement_segment_display_prefers_remote_error_over_id_fallback(self):
        segment = {
            "status": "failed",
            "errorId": "err-segment",
            "remoteErrorId": "err-remote",
            "remoteError": "kwvideo-v2-quannengcankao 生成失败:status=错误; message=请求失败，因为输入视频可能包含真人。",
        }

        display = self.client._replacement_segment_display_error(segment)

        self.assertIn("请求失败，因为输入视频可能包含真人", display)
        self.assertNotIn("错误编号", display)
        self.assertNotIn("err-segment", display)
        self.assertNotIn("err-remote", display)

    def test_segment_status_text_includes_drift_retry_and_block_reason(self):
        job = {"identityMode": "standard", "segments": [{"index": 1}]}
        segment = {
            "index": 1,
            "status": "failed",
            "driftRetryCount": 1,
            "retryReason": "visual_drift_blocked",
            "blockedReason": "visual_drift_retry_exhausted",
            "visualDriftQc": {"severeDrift": True, "reason": "汽车销售变成美妆带货"},
        }

        text = self.client._replacement_segment_status_text(job, segment)

        self.assertIn("跑偏重试 1 次", text)
        self.assertIn("已阻断合成", text)
        self.assertIn("汽车销售变成美妆带货", text)

    def test_error_text_localizes_visual_drift_codes(self):
        self.assertIn("偏离原视频主题", self.client._localize_replacement_display_text("visual_drift_blocked"))
        self.assertIn("重试后仍偏离", self.client._localize_replacement_display_text("visual_drift_retry_exhausted"))
        self.assertIn("参考图", self.client._localize_replacement_display_text("reference_mismatch"))

    def test_upstream_preflight_blocks_zero_balance_before_generation(self):
        with mock.patch.object(self.client, "fetch_balance", return_value=0), \
                mock.patch.object(self.client, "api") as api_call:
            result = self.client._replacement_upstream_preflight({"id": "job-balance"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "insufficient_balance")
        self.assertFalse(result["retryable"])
        self.assertIn("余额不足", result["summary"])
        self.assertIn("充值", result["nextAction"])
        api_call.assert_not_called()

    def test_replacement_error_display_localizes_upstream_billing_codes(self):
        self.assertIn(
            "余额不足",
            self.client._localize_replacement_display_text(
                'HTTP 402 {"error":"insufficient_balance","message":"Insufficient balance"}'
            ),
        )
        self.assertIn("模型未配置价格", self.client._localize_replacement_display_text("model_not_priced"))
        self.assertIn("上游账号未配置", self.client._localize_replacement_display_text("lk888_not_configured"))

    def test_replacement_diagnostics_summary_counts_failed_segments(self):
        job = {
            "error": "insufficient_balance",
            "errorId": "err-balance",
            "segments": [
                {"index": 1, "status": "done"},
                {"index": 2, "status": "failed", "error": "role_mismatch", "errorId": "err-seg-2"},
            ],
        }

        diagnostics = self.client._replacement_diagnostics_summary(job)

        self.assertEqual(diagnostics["errorId"], "err-balance")
        self.assertEqual(diagnostics["failedSegments"], [2])
        self.assertIn("余额不足", diagnostics["summary"])
        self.assertIn("充值", diagnostics["nextAction"])

    def test_start_generation_runs_upstream_preflight_before_uploading_references(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("        def work():", src.index("    def start_generation(self):"))
        end = src.index("        run_bg(work)", start)
        body = src[start:end]

        self.assertIn("_replacement_upstream_preflight", body)
        self.assertLess(body.index("_replacement_upstream_preflight"), body.index("self._upload_refs("))

    def test_start_generation_preflight_failure_saves_diagnostics_without_uploading(self):
        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._busy = False
        page._job = {
            "id": "job-preflight",
            "segments": [{"index": 1, "start": 0, "end": 1, "status": "planned"}],
            "outDir": tempfile.gettempdir(),
        }
        page._source = {
            "sourceVideoPath": __file__,
            "sourceUrl": "https://example.com/source.mp4",
            "breakdownAnalysis": {"meta": {"duration": 1}},
        }
        page._product_paths = [__file__]
        page._product_urls = []
        page._face_paths = []
        page._face_urls = []
        page._face_url = ""
        page._virtual_url = ""
        page._scene_path = ""
        page._scene_url = ""
        page.no_person_mode = _FakeWidget(checked=True)
        page.identity_mode = _FakeWidget(data="standard")
        page.face_authorized = _FakeWidget(checked=True)
        page.target_person = _FakeWidget(data="")
        page.scene_prompt = _FakeWidget("")
        page.status = _FakeWidget()
        page.b_retry_failed = _FakeWidget()
        page.b_review = _FakeWidget()
        page.b_start = _FakeWidget()
        page.b_cancel = _FakeWidget()
        page.progress_bar = _FakeWidget()
        page.progress_detail = _FakeWidget()
        page.table = _FakeTable()
        page._cancel_requested = False
        emitted = []
        saved = []
        bridge = types.SimpleNamespace(payload=types.SimpleNamespace(
            emit=lambda tag, payload: emitted.append((tag, payload))
        ))

        with mock.patch.object(self.client, "run_bg", side_effect=lambda fn: fn()), \
                mock.patch.object(self.client, "_replacement_upstream_preflight", return_value={
                    "ok": False,
                    "code": "insufficient_balance",
                    "summary": "上游余额不足，请充值后重试。",
                    "retryable": False,
                    "nextAction": "充值后重新执行替换生成",
                }), \
                mock.patch.object(page, "_upload_refs", side_effect=AssertionError("upload should not run")), \
                mock.patch.object(self.client, "_save_replacement_job", side_effect=lambda job: saved.append(dict(job))), \
                mock.patch.object(self.client, "BRIDGE", bridge):
            page.start_generation()

        self.assertEqual(saved[-1]["status"], "failed")
        self.assertEqual(saved[-1]["upstreamPreflight"]["code"], "insufficient_balance")
        self.assertIn("diagnostics", saved[-1])
        self.assertTrue(saved[-1]["errorId"].startswith("err-"))
        self.assertEqual(emitted[-1][0], "video_replace_done")
        self.assertEqual(emitted[-1][1]["job"]["diagnostics"]["retryable"], False)

    def test_cancel_generation_while_busy_persists_and_updates_feedback(self):
        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._busy = True
        page._cancel_requested = False
        page._job = {
            "id": "job-cancel",
            "status": "running",
            "segments": [{"index": 1, "status": "running", "stage": "principal_video_edit"}],
        }
        page.status = _FakeWidget()
        page.b_cancel = _FakeWidget("取消任务")
        page.progress = _FakeProgress()
        page.progress_detail = _FakeWidget()
        page.refresh_segments = mock.Mock()
        saved = []
        emitted = []
        bridge = types.SimpleNamespace(payload=types.SimpleNamespace(
            emit=lambda tag, payload: emitted.append((tag, payload))
        ))

        with mock.patch.object(self.client, "_save_replacement_job", side_effect=lambda job: saved.append(dict(job))), \
                mock.patch.object(self.client, "BRIDGE", bridge):
            page.cancel_generation()

        self.assertTrue(page._cancel_requested)
        self.assertTrue(page._job["cancelRequested"])
        self.assertEqual(page._job["status"], "cancel_requested")
        self.assertEqual(saved[-1]["status"], "cancel_requested")
        self.assertEqual(page.b_cancel.text(), "取消中")
        self.assertFalse(page.b_cancel.enabled)
        self.assertIn("当前远程片段结束后停止", page.status.text())
        self.assertIn("当前远程片段结束后停止", page.progress.format)
        self.assertEqual(emitted[-1][0], "video_replace_progress")
        self.assertEqual(emitted[-1][1]["stage"], "cancel_requested")

    def test_principal_start_generation_does_not_require_product_reference(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as td:
            person = Path(td) / "person.png"
            Image.new("RGB", (160, 240), (20, 40, 60)).save(person)
            page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
            page._busy = False
            page._job = {
                "id": "job-principal-no-product",
                "principalReplacementMode": "source_video_edit",
                "principalActor": {"status": "detected", "description": "main presenter"},
                "segments": [{"index": 1, "start": 0, "end": 1, "status": "planned"}],
                "outDir": td,
            }
            page._product_paths = []
            page._product_urls = []
            page._face_paths = [str(person)]
            page._face_urls = []
            page._face_url = ""
            page._virtual_url = ""
            page._scene_path = ""
            page._scene_url = ""
            page.no_person_mode = _FakeWidget(checked=False)
            page.identity_mode = _FakeWidget(data="fast")
            page.action_control = _FakeWidget(checked=False)
            page.product_anchor = _FakeWidget(checked=False)
            page.person_full_body = _FakeWidget(checked=True)
            page.face_authorized = _FakeWidget(checked=True)
            page.target_person = _FakeComboBox()
            page.scene_prompt = _FakeWidget("")
            page.status = _FakeWidget()
            page.b_retry_failed = _FakeWidget()
            page.b_review = _FakeWidget()
            page.b_start = _FakeWidget()
            page.b_cancel = _FakeWidget()
            page.progress = _FakeWidget()
            page.progress_detail = _FakeWidget()
            page.table = _FakeTable()
            page._cancel_requested = False
            page._collect_plan_edits = mock.Mock()
            page._set_generation_feedback = mock.Mock()
            page._warn_generation_blocked = mock.Mock()

            with mock.patch.dict(os.environ, {"VIDEO_REPLACE_PRINCIPAL_REPLACEMENT": "1"}, clear=False), \
                    mock.patch.object(self.client, "run_bg") as run_bg:
                page.start_generation()

        page._warn_generation_blocked.assert_not_called()
        run_bg.assert_called_once()

    def test_build_job_saves_selected_task_replacement_model(self):
        with tempfile.TemporaryDirectory() as td:
            page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
            page._source = {
                "sourceVideoPath": __file__,
                "sourceUrl": "https://example.com/source.mp4",
                "breakdownAnalysis": {"meta": {"duration": 8}},
            }
            page._job = {
                "id": "job-selected-model",
                "outDir": td,
                "principalReplacementMode": "source_video_edit",
                "principalActor": {"status": "detected", "description": "main presenter"},
                "segments": [{"index": 1, "start": 0, "end": 8, "duration": 8, "status": "planned"}],
            }
            page._product_paths = []
            page._product_urls = []
            page._face_paths = [__file__]
            page._face_urls = ["https://example.com/person.png"]
            page._face_url = "https://example.com/person.png"
            page._virtual_url = ""
            page._scene_path = ""
            page._scene_url = ""
            page.no_person_mode = _FakeWidget(checked=False)
            page.person_full_body = _FakeWidget(checked=True)
            page.replacement_model = _FakeWidget(data="sd20-all-reference")
            page.audio_mode = _FakeWidget(data="source")
            page.replacement_voice = _FakeWidget(data="Zephyr")

            with mock.patch.dict(os.environ, {"VIDEO_REPLACE_PRINCIPAL_REPLACEMENT": "1"}, clear=False):
                job = page._build_job()

        self.assertEqual(job["model"], "sd20-all-reference")

    def test_start_generation_blocks_tts_script_that_exceeds_segment_duration(self):
        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._busy = False
        page._job = {
            "id": "job-tts-too-long",
            "segments": [
                {
                    "index": 1,
                    "start": 0,
                    "end": 8,
                    "duration": 8,
                    "status": "planned",
                    "script": (
                        "这是一段明显超过八秒的中文口播内容，需要讲清楚产品卖点、使用场景、价格优势和购买引导，"
                        "还要继续说明限时政策、厂补叠加、金融方案、置换福利、到店礼、试驾预约和售后保障。"
                    ),
                }
            ],
            "outDir": tempfile.gettempdir(),
        }
        page._source = {
            "sourceVideoPath": __file__,
            "sourceUrl": "https://example.com/source.mp4",
            "breakdownAnalysis": {"meta": {"duration": 8}},
        }
        page._product_paths = [__file__]
        page._product_urls = []
        page._face_paths = []
        page._face_urls = []
        page._face_url = ""
        page._virtual_url = ""
        page._scene_path = ""
        page._scene_url = ""
        page.no_person_mode = _FakeWidget(checked=True)
        page.face_authorized = _FakeWidget(checked=True)
        page.target_person = _FakeComboBox()
        page.audio_mode = _FakeWidget(data="tts")
        page.replacement_voice = _FakeWidget(data="Zephyr")
        page.scene_prompt = _FakeWidget("")
        page.status = _FakeWidget()
        page.b_retry_failed = _FakeWidget()
        page.b_review = _FakeWidget()
        page.b_start = _FakeWidget()
        page.b_cancel = _FakeWidget()
        page.progress = _FakeWidget()
        page.progress_detail = _FakeWidget()
        page.table = _FakeTable()
        page._cancel_requested = False
        page._collect_plan_edits = mock.Mock()
        page._set_generation_feedback = mock.Mock()
        page._warn_generation_blocked = mock.Mock()

        with mock.patch.object(self.client, "run_bg") as run_bg:
            page.start_generation()

        page._warn_generation_blocked.assert_called_once()
        self.assertIn("超过自动提速上限", page._warn_generation_blocked.call_args.args[0])
        run_bg.assert_not_called()

    def test_generation_result_ignores_legacy_non_dict_diagnostics(self):
        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._job = {"status": "failed", "diagnostics": "legacy-bad-value"}

        with mock.patch.object(self.client.QtWidgets.QMessageBox, "warning") as warning:
            page._show_generation_result("生成失败", False)

        warning.assert_called_once()

    def test_replacement_progress_text_shows_elapsed_and_eta(self):
        text = self.client._replacement_progress_text(
            "生成片段 1/8：生成替换关键帧",
            {"elapsedSec": 65, "etaSec": 125, "stage": "keyframing"},
        )

        self.assertIn("生成替换关键帧", text)
        self.assertIn("已用时 1分05秒", text)
        self.assertIn("预计剩余 2分05秒", text)

    def test_high_identity_legacy_talking_segment_uses_replacement_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            segment = {
                "index": 1,
                "segmentType": "talking",
                "script": "新的产品口播",
                "prompt": "stable presenter",
                "audioStatus": "pending",
                "qcStatus": "pending",
            }
            job = {
                "identityMode": "high",
                "enableFaceFusion": True,
                "outDir": td,
                "segments": [segment],
                "modelFaceUrl": "https://x/face.png",
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
                "facefusionConfig": {"bin": "/tmp/ff", "modelDir": "/tmp/models", "licenseRef": "license", "providers": ["cpu"]},
            }
            order = []

            with mock.patch.object(self.client, "_run_hybrid_talking_segment") as human, \
                    mock.patch.object(self.client, "_run_hybrid_non_talking_segment",
                                      side_effect=lambda _job, _segment: order.append("non_talking") or str(Path(td) / "edited.mp4")):
                result = self.client._run_hybrid_replacement_segment(job, segment)

        self.assertTrue(result["ok"])
        self.assertEqual(order, ["non_talking"])
        self.assertEqual(segment["segmentType"], "non_talking")
        human.assert_not_called()

    def test_standard_legacy_talking_segment_uses_replacement_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            segment = {
                "index": 1,
                "segmentType": "talking",
                "script": "新的产品口播",
                "prompt": "stable presenter",
                "audioStatus": "pending",
                "qcStatus": "pending",
            }
            job = {
                "identityMode": "standard",
                "outDir": td,
                "segments": [segment],
                "modelFaceUrl": "https://x/face.png",
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
            }
            order = []

            with mock.patch.object(self.client, "_run_hybrid_talking_segment") as human, \
                    mock.patch.object(self.client, "_run_hybrid_non_talking_segment",
                                      side_effect=lambda _job, _segment: order.append("non_talking") or str(Path(td) / "edited.mp4")):
                result = self.client._run_hybrid_replacement_segment(job, segment)

        self.assertTrue(result["ok"])
        self.assertEqual(order, ["non_talking"])
        self.assertEqual(segment["segmentType"], "non_talking")
        human.assert_not_called()

    def test_segment_status_text_includes_model_warnings_and_remote_error(self):
        job = {"segments": [{"index": 1}, {"index": 2}]}
        segment = {
            "index": 1,
            "status": "video_edit",
            "stageLabel": "远程视频编辑",
            "elapsedSec": 65,
            "etaSec": 125,
            "model": "wan2.7-cankaosheng",
            "qcWarnings": [{"code": "product_mismatch", "reason": "产品不一致"}],
            "remoteErrorId": "err-remote-first",
            "remoteError": "上游队列繁忙",
        }

        text = self.client._replacement_segment_status_text(job, segment)

        self.assertIn("1/2", text)
        self.assertIn("远程视频编辑", text)
        self.assertIn("wan2.7-cankaosheng", text)
        self.assertIn("已用 1分05秒", text)
        self.assertIn("剩余 2分05秒", text)
        self.assertIn("质检提醒", text)
        self.assertIn("上游队列繁忙", text)
        self.assertNotIn("错误编号", text)
        self.assertNotIn("err-remote-first", text)

    def test_segment_status_text_includes_identity_mode(self):
        job = {"identityMode": "standard", "segments": [{"index": 1}]}
        segment = {"index": 1, "status": "video_edit", "model": "viduq3-turbo-cankaosheng"}

        text = self.client._replacement_segment_status_text(job, segment)

        self.assertIn("标准模式", text)

    def test_replacement_timing_snapshot_estimates_remaining_segments(self):
        job = {
            "startedAt": 1000.0,
            "segments": [
                {"index": 1, "segmentType": "talking", "status": "keyframing", "segmentStartedAt": 1010.0},
                {"index": 2, "segmentType": "non_talking", "status": "pending"},
            ],
        }

        timing = self.client._replacement_timing_snapshot(
            job, job["segments"][0], stage="keyframing", now=1070.0
        )

        self.assertEqual(timing["elapsedSec"], 70)
        self.assertGreater(timing["etaSec"], 0)
        self.assertEqual(timing["stage"], "keyframing")

    def test_mock_hybrid_pipeline_builds_audible_twelve_second_video(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            talking_input = root / "talking-input.mp4"
            motion_input = root / "motion-input.mp4"
            output = root / "final.mp4"
            make_tone_video(self.client, talking_input, duration=6, frequency=440)
            make_tone_video(self.client, motion_input, duration=6, frequency=660)
            with mock.patch.dict(os.environ, {"VIDEO_REPLACE_ENABLE_AVATAR_SEGMENTS": "1"}):
                segments = self.client._build_hybrid_replacement_plan({
                    "meta": {"duration": 12},
                    "transcript": {"segments": [{"startSec": 0, "endSec": 6, "text": "测试口播"}]},
                }, 12, segment_seconds=6)
            segments[0].update({"prompt": "talking", "sourceSegmentPath": str(talking_input)})
            segments[1].update({"prompt": "motion", "sourceSegmentPath": str(motion_input)})
            job = {
                "outDir": td,
                "segments": segments,
                "productImageUrls": ["https://x/product.png"],
                "sceneImageUrl": "https://x/scene.png",
                "faceSourcePaths": ["/tmp/f1.jpg", "/tmp/f2.jpg", "/tmp/f3.jpg"],
                "targetFaceReferencePath": "/tmp/target.jpg",
            }

            def download(url, path):
                shutil.copyfile(talking_input if "talking" in url else motion_input, path)
                return path

            def facefusion(input_path, output_path, _faces, _target, config=None):
                shutil.copyfile(input_path, output_path)
                return output_path

            qc = {"ok": True, "frames": ["first.jpg", "middle.jpg", "last.jpg"],
                  "checks": {"media": "passed", "audio": "passed"}}
            with mock.patch.object(self.client, "_ensure_replacement_keyframe", side_effect=lambda _j, s: s.update({
                    "keyframeUrl": "https://x/key.png"}) or "https://x/key.png"), \
                    mock.patch.object(self.client, "_run_hybrid_talking_segment", return_value="https://x/talking.mp4"), \
                    mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/source.mp4", {})), \
                    mock.patch.object(self.client, "lk888_media_task", return_value="https://x/edited.mp4"), \
                    mock.patch.object(self.client, "_wf_download", side_effect=download), \
                    mock.patch.object(self.client, "_run_facefusion", side_effect=facefusion), \
                    mock.patch.object(self.client, "_run_replacement_segment_qc", return_value=qc):
                first = self.client._run_hybrid_replacement_segment(job, segments[0])
                second = self.client._run_hybrid_replacement_segment(job, segments[1])

            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            for segment in segments:
                segment["reviewApproved"] = True
            self.assertTrue(self.client._replacement_segments_ready_for_final(segments))
            self.client._concat_replacement_segments([s["videoPath"] for s in segments], str(output))
            validation = self.client.validate_video_file(str(output))

            self.assertTrue(validation["ok"])
            self.assertTrue(validation["hasAudio"])
            self.assertGreaterEqual(validation["duration"], 11.5)
            self.assertGreater(mean_volume_db(self.client, output), -45.0)

    def test_v2_ui_has_plan_review_scene_and_principal_person_inputs(self):
        src = CLIENT.read_text(encoding="utf-8")

        self.assertIn('self.b_plan = QtWidgets.QPushButton("生成替换方案")', src)
        self.assertIn('self.b_review = QtWidgets.QPushButton("确认片段并合成")', src)
        self.assertIn('self.b_scene = QtWidgets.QPushButton("上传场景图")', src)
        self.assertIn('self.scene_prompt = QtWidgets.QLineEdit()', src)
        self.assertIn('self._face_paths = []', src)
        self.assertIn('self.no_person_mode = QtWidgets.QCheckBox("纯产品视频（无人物）")', src)
        self.assertNotIn('self.action_control = QtWidgets.QCheckBox(', src)
        self.assertNotIn('self.product_anchor = QtWidgets.QCheckBox(', src)
        self.assertIn("先提取原片人物/产品/场景槽位", src)
        self.assertIn("提取原片人物/产品/场景槽位", src)
        self.assertNotIn('refs_l.addWidget(self.product_anchor', src)
        self.assertNotIn('refs_l.addWidget(self.action_control', src)
        self.assertIn('self.b_face = QtWidgets.QPushButton("上传主角正脸全身照")', src)
        self.assertIn('self.person_full_body = QtWidgets.QCheckBox("该人物图为清晰正脸全身照（已确认）")', src)
        self.assertNotIn('self.principal_actor_lab = QtWidgets.QLabel("原片主角：尚未提取")', src)
        self.assertIn('"productAnchorEnabled": False', src)
        self.assertNotIn('self.identity_mode = QtWidgets.QComboBox()', src)
        self.assertNotIn('self.identity_mode.addItem(', src)
        self.assertNotIn('if not no_person_mode and not self._scene_path:', src)
        self.assertIn('"video_replace_plan_ready"', src)
        self.assertIn('"awaiting_review"', src)
        self.assertIn('"scenePrompt": self._job.get("scenePrompt") or ""', src)
        self.assertIn('"noPersonMode": no_person_mode', src)
        self.assertIn('"identityMode": "standard"', src)
        self.assertIn('"actionControlEnabled": False', src)
        self.assertNotIn('identity_mode in ("standard", "high")', src)
        self.assertNotIn('enable_facefusion = bool(facefusion_requested and _facefusion_preflight().get("ok"))', src)
        self.assertIn('"enableFaceFusion": False', src)
        self.assertIn('"principalActor": dict(self._job.get("principalActor") or {})', src)
        self.assertIn('"personReferencePaths": [] if no_person_mode else list(self._face_paths[:1])', src)
        self.assertNotIn("旧版同款替换需要三张授权人脸照片", src)
        self.assertIn('"principalReplacementMode": "source_video_edit" if principal_enabled else ""', src)
        self.assertIn('"productPreprocess": list(self._job.get("productPreprocess") or [])', src)
        self.assertIn('"noPersonMode": no_person_mode', src)
        self.assertIn('"targetFaceReferencePath": ""', src)
        self.assertIn('self.progress_detail = QtWidgets.QLabel("用时: - · 预计剩余: -")', src)
        self.assertIn('"耗时/预计"', src)
        self.assertIn("_replacement_progress_text", src)
        self.assertNotIn('self.principal_actor_preview = QtWidgets.QLabel("暂无预览")', src)
        self.assertNotIn("self.principal_actor_preview.setFixedSize(144, 180)", src)
        self.assertNotIn('refs_l.addWidget(self.principal_actor_preview', src)
        self.assertNotIn('refs_l.addWidget(self.principal_actor_lab', src)
        self.assertNotIn('refs_l.addWidget(QtWidgets.QLabel("原片主角确认")', src)
        self.assertNotIn('refs_l.addWidget(self.target_person', src)
        self.assertNotIn('self.target_person = QtWidgets.QComboBox()', src)
        self.assertNotIn("漫剧项目模式：使用上传人物图作为角色参考", src)

    def test_low_confidence_principal_actor_no_longer_requires_visible_candidate_selection(self):
        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._busy = True
        page._job = {"id": "job-manual-actor"}
        page._target_candidates = []
        page._principal_actor = {}
        page.status = _FakeWidget()
        page.b_start = _FakeWidget()
        page.refresh_segments = mock.Mock()
        page._set_generation_feedback = mock.Mock()

        page._on("video_replace_plan_ready", {
            "jobId": "job-manual-actor",
            "job": {"principalActor": {"status": "manual_required", "previewPath": "preview.jpg"}},
            "targetCandidates": ["candidate-1.jpg", "candidate-2.jpg"],
        })

        self.assertEqual(page._target_candidates, ["candidate-1.jpg", "candidate-2.jpg"])
        self.assertEqual(page._principal_actor["status"], "manual")
        self.assertEqual(page._principal_actor["manualFramePath"], "candidate-1.jpg")
        page.refresh_segments.assert_called_once()
        self.assertTrue(page.b_start.enabled)

    def test_hybrid_video_edit_prompt_treats_scene_reference_as_optional_source_compatible(self):
        job = {
            "productImageUrls": ["https://x/car.png"],
            "modelFaceUrl": "https://x/face.png",
            "sceneImageUrl": "https://x/showroom.png",
            "scenePrompt": "bright indoor showroom",
            "referenceModel": "viduq3-turbo-cankaosheng",
        }
        segment = {"duration": 8, "prompt": "base segment prompt"}

        _model, payload = self.client._build_hybrid_video_edit_request(
            job, segment, "https://x/source-car-interior.mp4")

        self.assertIn("https://x/showroom.png", payload["image_urls"])
        self.assertIn("必须将原片场景槽位替换为上传场景", payload["prompt"])
        self.assertIn("未上传场景图时才保留源视频场景", payload["prompt"])
        self.assertNotIn("Replace the environment with this scene", payload["prompt"])

    def test_start_generation_keeps_removed_identity_controls_disabled(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("    def start_generation(self):")
        end = src.index("        def work():", start)
        body = src[start:end]

        self.assertNotIn("facefusion_job = dict(self._job", body)
        self.assertNotIn("facefusion_requested", body)
        self.assertNotIn("_facefusion_preflight()", body)
        self.assertIn('self._job["identityMode"] = "standard"', body)
        self.assertIn('self._job["enableFaceFusion"] = False', body)
        self.assertIn('self._job["actionControlEnabled"] = False', body)
        self.assertIn('self._job["productAnchorEnabled"] = False', body)
        self.assertIn('self._job["targetFaceReferencePath"] = ""', body)
    def test_comic_video_preview_size_preserves_portrait_and_landscape_ratios(self):
        portrait = self.client._comic_video_preview_size(1080, 1920, 1000, 800)
        landscape = self.client._comic_video_preview_size(1920, 1080, 1000, 800)

        self.assertLess(portrait.width(), portrait.height())
        self.assertGreater(landscape.width(), landscape.height())
        self.assertAlmostEqual(portrait.width() / portrait.height(), 1080 / 1920, places=2)
        self.assertAlmostEqual(landscape.width() / landscape.height(), 1920 / 1080, places=2)
        for size in (portrait, landscape):
            self.assertLessEqual(size.width(), 820)
            self.assertLessEqual(size.height(), 656)

    @unittest.skipUnless(qt_runtime_available(), "PySide6 runtime unavailable")
    def test_comic_video_preview_uses_stable_window_parent(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = self.client.QtWidgets.QApplication.instance() or self.client.QtWidgets.QApplication([])
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "portrait.mp4")
            Path(path).write_bytes(b"video-placeholder")
            root = self.client.QtWidgets.QWidget()
            cell = self.client.ComicSegmentVideoCell.__new__(self.client.ComicSegmentVideoCell)
            self.client.QtWidgets.QWidget.__init__(cell, root)
            cell._video_path = path
            cell.segment = {"index": 1}
            with mock.patch.object(self.client, "ComicVideoPreviewDialog") as preview_dialog:
                cell._open_preview()

            preview_dialog.assert_called_once_with(path, root)
            preview_dialog.return_value.exec.assert_called_once_with()
            root.close()
            app.processEvents()

    # --- Task 6: Qt shared-service adapter and rollback switch ---

    def test_new_job_mode_defaults_to_legacy_when_unset(self):
        env = dict(os.environ)
        env.pop("VIDEO_REPLACEMENT_SERVICE_MODE", None)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(self.client.replacement_mode_for_new_job(), "legacy")
            self.assertFalse(self.client.video_replacement_service_shared())

    def test_legacy_mode_keeps_old_path(self):
        with mock.patch.dict(os.environ, {"VIDEO_REPLACEMENT_SERVICE_MODE": "legacy"}):
            self.assertEqual(self.client.replacement_mode_for_new_job(), "legacy")
            self.assertFalse(self.client.video_replacement_service_shared())

    def test_shared_mode_selected_only_by_explicit_env(self):
        with mock.patch.dict(os.environ, {"VIDEO_REPLACEMENT_SERVICE_MODE": "SHARED"}):
            self.assertEqual(self.client.replacement_mode_for_new_job(), "shared")
            self.assertTrue(self.client.video_replacement_service_shared())
        with mock.patch.dict(os.environ, {"VIDEO_REPLACEMENT_SERVICE_MODE": "bogus"}):
            self.assertEqual(self.client.replacement_mode_for_new_job(), "legacy")
            self.assertFalse(self.client.video_replacement_service_shared())

    def test_shared_mode_routes_qt_to_service(self):
        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._job = {"id": "rvw_test", "status": "planned", "segments": [{"index": 1}]}
        page._service_adapter = mock.Mock()

        page._start_shared_service_job()

        page._service_adapter.execute.assert_called_once_with(
            "rvw_test", {}, progress=page._emit_service_progress
        )

    def test_emit_service_progress_keeps_video_replace_progress_shape(self):
        page = self.client.VideoReplacementPage.__new__(self.client.VideoReplacementPage)
        page._job = {"id": "rvw_test", "segments": [{"index": 1, "status": "editing"}]}
        bridge, events = _recording_bridge()
        segments = [{"index": 1, "status": "editing", "prompt": "镜头1"}]
        with mock.patch.object(self.client, "BRIDGE", bridge):
            page._emit_service_progress("rvw_test", "editing", "生成片段 1/1", 1, segments)

        self.assertEqual(len(events), 1)
        tag, payload = events[0]
        self.assertEqual(tag, "video_replace_progress")
        self.assertEqual(payload["jobId"], "rvw_test")
        self.assertEqual(payload["segments"], segments)
        self.assertEqual(payload["prompt"], "镜头1")
        self.assertIn("timing", payload)
        self.assertIn("message", payload)
        self.assertIn("stage", payload)

    def test_start_generation_gates_shared_service_and_preserves_legacy_dispatch(self):
        src = CLIENT.read_text(encoding="utf-8")
        start = src.index("    def start_generation(self):")
        body = src[start:src.index("\n    def _run_job_segments", start)]

        self.assertIn("if video_replacement_service_shared():", body)
        self.assertIn("run_bg(self._start_shared_service_job)", body)
        self.assertIn("run_bg(work)", body)
        self.assertLess(
            body.index("run_bg(self._start_shared_service_job)"),
            body.index("        run_bg(work)"),
        )

    def test_service_adapter_maps_lifecycle_and_emits_redacted_bridge_events(self):
        service_mod = load_replacement_service()
        with tempfile.TemporaryDirectory() as td:
            service = service_mod.ReplacementService(
                data_dir=td,
                source_resolver=_AdapterFakeSourceResolver(),
                pipeline=_AdapterFakePipeline(),
            )
            bridge, events = _recording_bridge()
            adapter = self.client.ReplacementServiceAdapter(service=service, bridge=bridge)

            prepared = adapter.prepare(
                "job-adapter-1",
                {"sourceUrl": "https://example.test/video.mp4"},
                [("characterImage", "face.png", b"img")],
            )
            self.assertEqual(prepared["status"], "planned")
            self.assertNotIn("outDir", prepared)
            self.assertNotIn("sourceVideoPath", prepared)

            running = adapter.execute("job-adapter-1", {"note": "keep"}, progress=None)
            self.assertEqual(running["status"], "awaiting_review")

            completed = adapter.concat("job-adapter-1")
            self.assertEqual(completed["status"], "completed")

            tags = [tag for tag, _ in events]
            self.assertIn("video_replace_plan_ready", tags)
            # awaiting_review is surfaced through progress, not a done event
            self.assertEqual(tags.count("video_replace_done"), 1)
            dump = json.dumps(events, ensure_ascii=False)
            for leak in ("outDir", "sourceVideoPath", "videoPath", "outputPath", td):
                self.assertNotIn(leak, dump)

    def test_service_adapter_execute_partial_emits_failed_segments(self):
        service = mock.Mock()
        service.execute.return_value = {
            "id": "job-x",
            "status": "partial",
            "segments": [
                {"index": 1, "status": "done"},
                {"index": 2, "status": "failed", "error": "provider failed"},
            ],
        }
        bridge, events = _recording_bridge()
        adapter = self.client.ReplacementServiceAdapter(service=service, bridge=bridge)
        progress = lambda *args, **kwargs: None

        adapter.execute("job-x", {}, progress=progress)

        service.execute.assert_called_once_with("job-x", overrides={}, progress=progress)
        done = [payload for tag, payload in events if tag == "video_replace_done"]
        self.assertEqual(len(done), 1)
        self.assertEqual(len(done[0]["failedSegments"]), 1)
        self.assertEqual(done[0]["failedSegments"][0]["index"], 2)

    def test_service_adapter_retry_and_cancel_map_to_service(self):
        service = mock.Mock()
        service.retry.return_value = {"id": "job-x", "status": "partial", "segments": []}
        service.cancel.return_value = {"id": "job-x", "status": "cancelled", "segments": []}
        bridge, events = _recording_bridge()
        adapter = self.client.ReplacementServiceAdapter(service=service, bridge=bridge)
        progress = lambda *args, **kwargs: None

        adapter.retry("job-x", [2], progress=progress)
        adapter.cancel("job-x")

        service.retry.assert_called_once_with("job-x", [2], progress=progress)
        service.cancel.assert_called_once_with("job-x")
        tags = [tag for tag, _ in events]
        self.assertIn("video_replace_done", tags)

    def test_replacement_web_download_source_returns_validated_path(self):
        with tempfile.TemporaryDirectory() as td:
            job_dir = os.path.join(td, "rvw_job")

            def fake_download(url, path):
                Path(path).write_bytes(b"fake-video-bytes")
                return path

            with mock.patch.object(self.client, "_wf_download", side_effect=fake_download) as download, \
                    mock.patch.object(
                        self.client,
                        "_breakdown_source_validation",
                        return_value={"ok": True, "duration": 8.0, "width": 720, "height": 1280},
                    ) as validate:
                path = self.client._replacement_web_download_source(
                    "https://www.douyin.com/video/abc.mp4", job_dir
                )

            self.assertEqual(download.call_count, 1)
            self.assertEqual(validate.call_count, 1)
            self.assertTrue(os.path.isfile(path))
            self.assertTrue(os.path.abspath(path).startswith(os.path.abspath(job_dir) + os.sep))

    def test_replacement_web_download_source_rejects_invalid_media(self):
        with tempfile.TemporaryDirectory() as td:
            job_dir = os.path.join(td, "rvw_job")

            def fake_download(url, path):
                Path(path).write_bytes(b"<html>403</html>")
                return path

            with mock.patch.object(self.client, "_wf_download", side_effect=fake_download), \
                    mock.patch.object(
                        self.client,
                        "_breakdown_source_validation",
                        return_value={"ok": False, "code": "download_html_body"},
                    ):
                with self.assertRaises(Exception) as ctx:
                    self.client._replacement_web_download_source(
                        "https://www.douyin.com/video/bad", job_dir
                    )

            self.assertIn("download_html_body", str(ctx.exception))
            leftovers = [
                name for name in os.listdir(job_dir)
                if name.lower().endswith((".mp4", ".mov", ".webm", ".m4v"))
            ]
            self.assertEqual(leftovers, [])

    def test_replacement_web_download_source_rejects_non_http_url(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(self.client, "_wf_download", side_effect=AssertionError("must not download")):
                with self.assertRaises(ValueError):
                    self.client._replacement_web_download_source(
                        "file:///etc/passwd", os.path.join(td, "rvw_job")
                    )


if __name__ == "__main__":
    unittest.main()
