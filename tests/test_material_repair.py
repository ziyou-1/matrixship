import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import warnings


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def make_test_video(path, color="green"):
    import imageio_ffmpeg

    subprocess.run([
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c={color}:s=320x240:d=1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ], check=True, capture_output=True)


def make_test_image(path, color=(40, 160, 90)):
    from PIL import Image

    image = Image.new("RGB", (64, 48), color=color)
    image.save(path, format="JPEG")


def replace_list(target, values):
    target[:] = list(values)


def run_concurrently(callable_, count=2, timeout=15):
    results = [None] * count
    errors = []

    def runner(index):
        try:
            results[index] = callable_()
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=runner, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout)
    if any(thread.is_alive() for thread in threads):
        raise AssertionError("concurrent material import deadlocked")
    if errors:
        raise errors[0]
    return results


class MaterialRepairTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cls.api = importlib.import_module("api_server")
            cls.central = importlib.import_module("central_server")
        cls.validation = importlib.import_module("utils.media_validation")

    def require_repair_contract(self):
        self.assertTrue(hasattr(self.api, "MATERIAL_QUARANTINE_DIR"))
        self.assertTrue(hasattr(self.central, "MATERIAL_QUARANTINE_DIR"))

    def test_local_invalid_existing_material_is_repaired_without_id_change(self):
        self.require_repair_contract()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            quarantine = root / "quarantine"
            source = root / "download"
            old_id = "local-material-1"
            old_dir = materials / old_id
            old_dir.mkdir(parents=True)
            (old_dir / "video.mp4").write_text("<html>403 Forbidden</html>", encoding="utf-8")
            source.mkdir()
            make_test_video(source / "video.mp4")
            library = [{
                "id": old_id,
                "title": "old",
                "type": "video",
                "files": ["video.mp4"],
                "urls": [f"/api/library/file/{old_id}/video.mp4"],
                "published": 3,
                "createdAt": 123.0,
                "sourceDownloadKey": "https://www.douyin.com/video/1",
                "sourceDownloadPath": "/old/path",
            }]

            with mock.patch.object(self.api, "MATERIALS_DIR", str(materials)), \
                    mock.patch.object(self.api, "MATERIAL_QUARANTINE_DIR", str(quarantine)), \
                    mock.patch.object(self.api, "load_library", side_effect=lambda: list(library)), \
                    mock.patch.object(self.api, "save_library", side_effect=lambda rows: replace_list(library, rows)):
                repaired = self.api.import_download_to_library(
                    str(source),
                    {"title": "new", "nickname": "author"},
                    source_url="https://www.douyin.com/video/1",
                    platform="douyin",
                )

            repaired_path = materials / old_id / "video.mp4"
            self.assertEqual(repaired["id"], old_id)
            self.assertEqual(repaired["published"], 3)
            self.assertEqual(repaired["createdAt"], 123.0)
            self.assertTrue(repaired["repaired"])
            self.assertTrue(self.validation.validate_video_file(str(repaired_path))["ok"])
            self.assertTrue(list((quarantine / old_id).rglob("video.mp4")))
            self.assertEqual(library[0]["id"], old_id)

    def test_local_invalid_candidate_is_not_imported(self):
        self.require_repair_contract()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "download"
            source.mkdir()
            (source / "video.mp4").write_text("<html>403 Forbidden</html>", encoding="utf-8")
            library = []

            with mock.patch.object(self.api, "MATERIALS_DIR", str(root / "materials")), \
                    mock.patch.object(self.api, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.api, "load_library", side_effect=lambda: list(library)), \
                    mock.patch.object(self.api, "save_library", side_effect=lambda rows: replace_list(library, rows)):
                result = self.api.import_download_to_library(
                    str(source), {"title": "bad"}, source_url="https://www.douyin.com/video/bad"
                )

            self.assertIsNone(result)
            self.assertEqual(library, [])

    def test_local_image_repair_preserves_existing_media_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            source = root / "download"
            old_id = "local-image-repair"
            (materials / old_id).mkdir(parents=True)
            source.mkdir()
            make_test_image(source / "image.jpg")
            library = [{
                "id": old_id,
                "title": "old",
                "type": "image",
                "files": ["missing.jpg"],
                "duration": 12.5,
                "width": 1080,
                "height": 1920,
                "sourceDownloadKey": "image-repair-local",
            }]

            with mock.patch.object(self.api, "MATERIALS_DIR", str(materials)), \
                    mock.patch.object(self.api, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.api, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.api, "load_library", side_effect=lambda: list(library)), \
                    mock.patch.object(self.api, "save_library", side_effect=lambda rows: replace_list(library, rows)):
                repaired = self.api.import_download_to_library(
                    str(source), {"title": "new"}, source_url="image-repair-local"
                )

            self.assertEqual(repaired["duration"], 12.5)
            self.assertEqual(repaired["width"], 1080)
            self.assertEqual(repaired["height"], 1920)

    def test_local_invalid_image_candidate_is_not_imported(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "download"
            source.mkdir()
            (source / "image.jpg").write_bytes(b"not-a-real-image")
            library = []

            with mock.patch.object(self.api, "MATERIALS_DIR", str(root / "materials")), \
                    mock.patch.object(self.api, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.api, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.api, "load_library", side_effect=lambda: list(library)), \
                    mock.patch.object(self.api, "save_library", side_effect=lambda rows: replace_list(library, rows)):
                imported = self.api.import_download_to_library(
                    str(source), {"title": "bad image"}, source_url="invalid-image-local"
                )

            self.assertIsNone(imported)
            self.assertEqual(library, [])

    def test_local_concurrent_import_reuses_single_material_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "download"
            source.mkdir()
            make_test_video(source / "video.mp4")
            library = []
            barrier = threading.Barrier(2)
            original_copy = self.api._copy_or_link_file

            def synchronized_copy(src, dst):
                original_copy(src, dst)
                barrier.wait(timeout=10)

            with mock.patch.object(self.api, "MATERIALS_DIR", str(root / "materials")), \
                    mock.patch.object(self.api, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.api, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.api, "load_library", side_effect=lambda: list(library)), \
                    mock.patch.object(self.api, "save_library", side_effect=lambda rows: replace_list(library, rows)), \
                    mock.patch.object(self.api, "_copy_or_link_file", side_effect=synchronized_copy):
                results = run_concurrently(lambda: self.api.import_download_to_library(
                    str(source),
                    {"title": "same"},
                    source_url="https://www.douyin.com/video/concurrent-local",
                ))

            self.assertEqual(len(library), 1)
            self.assertEqual(len({item["id"] for item in results}), 1)
            self.assertEqual(results[0]["id"], library[0]["id"])

    def test_local_concurrent_repair_commits_once_and_reuses_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            source = root / "download"
            old_id = "local-concurrent-repair"
            old_dir = materials / old_id
            old_dir.mkdir(parents=True)
            old_path = old_dir / "video.mp4"
            old_path.write_text("<html>403 Forbidden</html>", encoding="utf-8")
            source.mkdir()
            make_test_video(source / "video.mp4")
            library = [{
                "id": old_id,
                "title": "old",
                "type": "video",
                "files": ["video.mp4"],
                "published": 2,
                "createdAt": 111.0,
                "sourceDownloadKey": "https://www.douyin.com/video/concurrent-repair-local",
            }]
            barrier = threading.Barrier(2)
            validation_calls = 0
            validation_lock = threading.Lock()
            original_validate = self.api.validate_video_file

            def synchronized_validate(path):
                nonlocal validation_calls
                result = original_validate(path)
                if os.path.normpath(path) == os.path.normpath(str(old_path)):
                    with validation_lock:
                        validation_calls += 1
                        wait_for_peer = validation_calls <= 2
                    if wait_for_peer:
                        barrier.wait(timeout=10)
                return result

            with mock.patch.object(self.api, "MATERIALS_DIR", str(materials)), \
                    mock.patch.object(self.api, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.api, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.api, "load_library", side_effect=lambda: list(library)), \
                    mock.patch.object(self.api, "save_library", side_effect=lambda rows: replace_list(library, rows)) as save_mock, \
                    mock.patch.object(self.api, "validate_video_file", side_effect=synchronized_validate):
                results = run_concurrently(lambda: self.api.import_download_to_library(
                    str(source),
                    {"title": "repaired"},
                    source_url="https://www.douyin.com/video/concurrent-repair-local",
                ))

            self.assertEqual(save_mock.call_count, 1)
            self.assertEqual(len(library), 1)
            self.assertEqual({item["id"] for item in results}, {old_id})
            self.assertTrue(self.validation.validate_video_file(str(old_path))["ok"])

    def test_local_new_import_rolls_back_memory_when_persist_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "download"
            source.mkdir()
            make_test_video(source / "video.mp4")
            memory = {"library": []}

            with mock.patch.object(self.api, "MATERIALS_DIR", str(root / "materials")), \
                    mock.patch.object(self.api, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.api, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.api, "_MEM", memory), \
                    mock.patch.object(self.api, "_save_json", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    self.api.import_download_to_library(
                        str(source),
                        {"title": "new"},
                        source_url="https://www.douyin.com/video/persist-failure-new",
                    )

            self.assertEqual(memory["library"], [])
            material_root = root / "materials"
            self.assertFalse(material_root.exists() and any(material_root.iterdir()))

    def test_local_repair_rolls_back_memory_when_persist_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            source = root / "download"
            old_id = "local-persist-failure-repair"
            old_dir = materials / old_id
            old_dir.mkdir(parents=True)
            old_path = old_dir / "video.mp4"
            make_test_video(old_path, color="red")
            old_bytes = old_path.read_bytes()
            source.mkdir()
            make_test_video(source / "video.mp4")
            old = {
                "id": old_id,
                "title": "old",
                "type": "video",
                "files": ["video.mp4"],
                "published": 7,
                "createdAt": 333.0,
                "sourceDownloadKey": "https://www.douyin.com/video/persist-failure-repair",
            }
            memory = {"library": [old]}
            original_validate = self.api.validate_video_file

            def force_repair(path):
                if os.path.normpath(path) == os.path.normpath(str(old_path)):
                    return {"ok": False, "code": "forced_repair"}
                return original_validate(path)

            with mock.patch.object(self.api, "MATERIALS_DIR", str(materials)), \
                    mock.patch.object(self.api, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.api, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.api, "_MEM", memory), \
                    mock.patch.object(self.api, "_save_json", side_effect=OSError("disk full")), \
                    mock.patch.object(self.api, "validate_video_file", side_effect=force_repair):
                with self.assertRaisesRegex(OSError, "disk full"):
                    self.api.import_download_to_library(
                        str(source),
                        {"title": "repaired"},
                        source_url=old["sourceDownloadKey"],
                    )

            self.assertEqual(memory["library"], [old])
            self.assertEqual(old_path.read_bytes(), old_bytes)
            self.assertTrue(self.validation.validate_video_file(str(old_path))["ok"])
            self.assertTrue(list((root / "quarantine" / old_id).rglob("video.mp4")))
            self.assertTrue(list((root / "quarantine" / old_id).rglob("metadata.json")))

    def test_local_repair_quarantine_copy_failure_keeps_old_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            source = root / "download"
            old_id = "local-quarantine-copy-failure"
            old_dir = materials / old_id
            old_dir.mkdir(parents=True)
            old_path = old_dir / "video.mp4"
            make_test_video(old_path, color="red")
            old_bytes = old_path.read_bytes()
            source.mkdir()
            make_test_video(source / "video.mp4")
            old = {"id": old_id, "type": "video", "files": ["video.mp4"], "sourceDownloadKey": "local-copy-failure"}
            library = [old]
            original_validate = self.api.validate_video_file
            original_copy = self.api.shutil.copy2

            def force_repair(path):
                if os.path.normpath(path) == os.path.normpath(str(old_path)):
                    return {"ok": False, "code": "forced_repair"}
                return original_validate(path)

            def fail_quarantine_copy(src, dst, *args, **kwargs):
                if os.path.normpath(str(root / "quarantine")) in os.path.normpath(dst):
                    raise OSError("quarantine copy failed")
                return original_copy(src, dst, *args, **kwargs)

            with mock.patch.object(self.api, "MATERIALS_DIR", str(materials)), \
                    mock.patch.object(self.api, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.api, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.api, "load_library", side_effect=lambda: list(library)), \
                    mock.patch.object(self.api, "save_library", side_effect=lambda rows: replace_list(library, rows)), \
                    mock.patch.object(self.api, "validate_video_file", side_effect=force_repair), \
                    mock.patch.object(self.api.shutil, "copy2", side_effect=fail_quarantine_copy):
                with self.assertRaisesRegex(OSError, "quarantine copy failed"):
                    self.api.import_download_to_library(
                        str(source), {"title": "new"}, source_url=old["sourceDownloadKey"]
                    )

            self.assertEqual(library, [old])
            self.assertEqual(old_path.read_bytes(), old_bytes)
            self.assertTrue(self.validation.validate_video_file(str(old_path))["ok"])

    def test_local_repair_metadata_failure_keeps_old_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            source = root / "download"
            old_id = "local-metadata-failure"
            old_dir = materials / old_id
            old_dir.mkdir(parents=True)
            old_path = old_dir / "video.mp4"
            make_test_video(old_path, color="red")
            old_bytes = old_path.read_bytes()
            source.mkdir()
            make_test_video(source / "video.mp4")
            old = {"id": old_id, "type": "video", "files": ["video.mp4"], "sourceDownloadKey": "local-metadata-failure"}
            library = [old]
            original_validate = self.api.validate_video_file
            original_replace = self.api.os.replace

            def force_repair(path):
                if os.path.normpath(path) == os.path.normpath(str(old_path)):
                    return {"ok": False, "code": "forced_repair"}
                return original_validate(path)

            def fail_metadata_commit(src, dst):
                if os.path.basename(dst) == "metadata.json":
                    raise OSError("metadata failed")
                return original_replace(src, dst)

            with mock.patch.object(self.api, "MATERIALS_DIR", str(materials)), \
                    mock.patch.object(self.api, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.api, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.api, "load_library", side_effect=lambda: list(library)), \
                    mock.patch.object(self.api, "save_library", side_effect=lambda rows: replace_list(library, rows)), \
                    mock.patch.object(self.api, "validate_video_file", side_effect=force_repair), \
                    mock.patch.object(self.api.os, "replace", side_effect=fail_metadata_commit):
                with self.assertRaisesRegex(OSError, "metadata failed"):
                    self.api.import_download_to_library(
                        str(source), {"title": "new"}, source_url=old["sourceDownloadKey"]
                    )

            self.assertEqual(library, [old])
            self.assertEqual(old_path.read_bytes(), old_bytes)
            self.assertTrue(self.validation.validate_video_file(str(old_path))["ok"])

    def test_local_repair_replace_failure_observes_old_file_in_place(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            source = root / "download"
            old_id = "local-replace-failure"
            old_dir = materials / old_id
            old_dir.mkdir(parents=True)
            old_path = old_dir / "video.mp4"
            make_test_video(old_path, color="red")
            old_bytes = old_path.read_bytes()
            source.mkdir()
            make_test_video(source / "video.mp4")
            old = {"id": old_id, "type": "video", "files": ["video.mp4"], "sourceDownloadKey": "local-replace-failure"}
            library = [old]
            observed_old_in_place = []
            original_validate = self.api.validate_video_file
            original_replace = self.api.os.replace

            def force_repair(path):
                if os.path.normpath(path) == os.path.normpath(str(old_path)):
                    return {"ok": False, "code": "forced_repair"}
                return original_validate(path)

            def fail_candidate_replace(src, dst):
                if ".incoming-" in src and os.path.normpath(dst) == os.path.normpath(str(old_path)):
                    observed_old_in_place.append(old_path.is_file() and old_path.read_bytes() == old_bytes)
                    raise OSError("replace failed")
                return original_replace(src, dst)

            with mock.patch.object(self.api, "MATERIALS_DIR", str(materials)), \
                    mock.patch.object(self.api, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.api, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.api, "load_library", side_effect=lambda: list(library)), \
                    mock.patch.object(self.api, "save_library", side_effect=lambda rows: replace_list(library, rows)), \
                    mock.patch.object(self.api, "validate_video_file", side_effect=force_repair), \
                    mock.patch.object(self.api.os, "replace", side_effect=fail_candidate_replace):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    self.api.import_download_to_library(
                        str(source), {"title": "new"}, source_url=old["sourceDownloadKey"]
                    )

            self.assertEqual(observed_old_in_place, [True])
            self.assertEqual(library, [old])
            self.assertEqual(old_path.read_bytes(), old_bytes)
            self.assertTrue(self.validation.validate_video_file(str(old_path))["ok"])

    def test_central_invalid_existing_material_is_repaired_without_id_change(self):
        self.require_repair_contract()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            quarantine = root / "quarantine"
            source = root / "download"
            old_id = "central-material-1"
            old_dir = materials / old_id
            old_dir.mkdir(parents=True)
            (old_dir / "video.mp4").write_text("<html>403 Forbidden</html>", encoding="utf-8")
            source.mkdir()
            make_test_video(source / "video.mp4")
            old = {
                "id": old_id,
                "orgId": "org-default",
                "title": "old",
                "type": "video",
                "files": ["video.mp4"],
                "published": 5,
                "createdAt": 456.0,
                "sourceDownloadKey": "https://www.douyin.com/video/1",
                "remoteMaterialId": "remote-1",
                "remoteNodeId": "node-1",
            }
            state = {"library": [old], "nodes": {}}
            result = {
                "ok": True,
                "savePath": str(source),
                "material": {
                    "id": "remote-1",
                    "title": "new",
                    "type": "video",
                    "files": ["video.mp4"],
                    "sourceDownloadKey": "https://www.douyin.com/video/1",
                    "sourceDownloadPath": str(source),
                    "sourceUrl": "https://www.douyin.com/video/1",
                },
            }

            with mock.patch.object(self.central, "MATERIALS_DIR", str(materials)), \
                    mock.patch.object(self.central, "MATERIAL_QUARANTINE_DIR", str(quarantine)), \
                    mock.patch.object(self.central, "STATE", state), \
                    mock.patch.object(self.central, "persist", return_value=None), \
                    mock.patch.object(self.central, "add_event", return_value=None):
                repaired = self.central.mirror_download_material_to_library(
                    result, "org-default", "node-1"
                )

            repaired_path = materials / old_id / "video.mp4"
            self.assertEqual(repaired["id"], old_id)
            self.assertEqual(repaired["published"], 5)
            self.assertEqual(repaired["createdAt"], 456.0)
            self.assertTrue(repaired["repaired"])
            self.assertTrue(self.validation.validate_video_file(str(repaired_path))["ok"])
            self.assertTrue(list((quarantine / old_id).rglob("video.mp4")))
            self.assertEqual(state["library"][0]["id"], old_id)

    def test_central_image_repair_preserves_existing_media_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            source = root / "download"
            old_id = "central-image-repair"
            (materials / old_id).mkdir(parents=True)
            source.mkdir()
            make_test_image(source / "image.jpg")
            old = {
                "id": old_id,
                "orgId": "org-default",
                "title": "old",
                "type": "image",
                "files": ["missing.jpg"],
                "duration": 9.5,
                "width": 720,
                "height": 1280,
                "sourceDownloadKey": "image-repair-central",
                "remoteMaterialId": "remote-image",
                "remoteNodeId": "node-1",
            }
            state = {"library": [old], "nodes": {}}
            result = {
                "ok": True,
                "savePath": str(source),
                "material": {
                    "id": "remote-image",
                    "title": "new",
                    "type": "image",
                    "files": ["image.jpg"],
                    "sourceDownloadKey": old["sourceDownloadKey"],
                    "sourceDownloadPath": str(source),
                },
            }

            with mock.patch.object(self.central, "MATERIALS_DIR", str(materials)), \
                    mock.patch.object(self.central, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.central, "STATE", state), \
                    mock.patch.object(self.central, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.central, "persist", return_value=None), \
                    mock.patch.object(self.central, "add_event", return_value=None):
                repaired = self.central.mirror_download_material_to_library(
                    result, "org-default", "node-1"
                )

            self.assertEqual(repaired["duration"], 9.5)
            self.assertEqual(repaired["width"], 720)
            self.assertEqual(repaired["height"], 1280)

    def test_central_invalid_image_candidate_is_not_imported(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "download"
            source.mkdir()
            (source / "image.jpg").write_bytes(b"not-a-real-image")
            state = {"library": [], "nodes": {}}
            result = {
                "ok": True,
                "savePath": str(source),
                "material": {
                    "id": "remote-invalid-image",
                    "title": "bad image",
                    "type": "image",
                    "files": ["image.jpg"],
                    "sourceDownloadKey": "invalid-image-central",
                    "sourceDownloadPath": str(source),
                },
            }

            with mock.patch.object(self.central, "MATERIALS_DIR", str(root / "materials")), \
                    mock.patch.object(self.central, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.central, "STATE", state), \
                    mock.patch.object(self.central, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.central, "persist", return_value=None), \
                    mock.patch.object(self.central, "add_event", return_value=None):
                imported = self.central.mirror_download_material_to_library(
                    result, "org-default", "node-1"
                )

            self.assertIsNone(imported)
            self.assertEqual(state["library"], [])

    def test_central_concurrent_mirror_reuses_single_material_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "download"
            source.mkdir()
            make_test_video(source / "video.mp4")
            state = {"library": [], "nodes": {}}
            result = {
                "ok": True,
                "savePath": str(source),
                "material": {
                    "id": "remote-concurrent",
                    "title": "same",
                    "type": "video",
                    "files": ["video.mp4"],
                    "sourceDownloadKey": "https://www.douyin.com/video/concurrent-central",
                    "sourceDownloadPath": str(source),
                },
            }
            barrier = threading.Barrier(2)
            original_copy = self.central.copy_or_link_file

            def synchronized_copy(src, dst):
                original_copy(src, dst)
                barrier.wait(timeout=10)

            with mock.patch.object(self.central, "MATERIALS_DIR", str(root / "materials")), \
                    mock.patch.object(self.central, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.central, "STATE", state), \
                    mock.patch.object(self.central, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.central, "persist", return_value=None), \
                    mock.patch.object(self.central, "add_event", return_value=None), \
                    mock.patch.object(self.central, "copy_or_link_file", side_effect=synchronized_copy):
                results = run_concurrently(lambda: self.central.mirror_download_material_to_library(
                    result, "org-default", "node-1"
                ))

            self.assertEqual(len(state["library"]), 1)
            self.assertEqual(len({item["id"] for item in results}), 1)
            self.assertEqual(results[0]["id"], state["library"][0]["id"])

    def test_central_concurrent_repair_commits_once_and_reuses_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            source = root / "download"
            old_id = "central-concurrent-repair"
            old_dir = materials / old_id
            old_dir.mkdir(parents=True)
            old_path = old_dir / "video.mp4"
            old_path.write_text("<html>403 Forbidden</html>", encoding="utf-8")
            source.mkdir()
            make_test_video(source / "video.mp4")
            old = {
                "id": old_id,
                "orgId": "org-default",
                "title": "old",
                "type": "video",
                "files": ["video.mp4"],
                "published": 4,
                "createdAt": 222.0,
                "sourceDownloadKey": "https://www.douyin.com/video/concurrent-repair-central",
                "remoteMaterialId": "remote-repair",
                "remoteNodeId": "node-1",
            }
            state = {"library": [old], "nodes": {}}
            result = {
                "ok": True,
                "savePath": str(source),
                "material": {
                    "id": "remote-repair",
                    "title": "repaired",
                    "type": "video",
                    "files": ["video.mp4"],
                    "sourceDownloadKey": old["sourceDownloadKey"],
                    "sourceDownloadPath": str(source),
                },
            }
            barrier = threading.Barrier(2)
            validation_calls = 0
            validation_lock = threading.Lock()
            original_validate = self.central.validate_video_file

            def synchronized_validate(path):
                nonlocal validation_calls
                validation = original_validate(path)
                if os.path.normpath(path) == os.path.normpath(str(old_path)):
                    with validation_lock:
                        validation_calls += 1
                        wait_for_peer = validation_calls <= 2
                    if wait_for_peer:
                        barrier.wait(timeout=10)
                return validation

            with mock.patch.object(self.central, "MATERIALS_DIR", str(materials)), \
                    mock.patch.object(self.central, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.central, "STATE", state), \
                    mock.patch.object(self.central, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.central, "persist", return_value=None) as persist_mock, \
                    mock.patch.object(self.central, "add_event", return_value=None), \
                    mock.patch.object(self.central, "validate_video_file", side_effect=synchronized_validate):
                results = run_concurrently(lambda: self.central.mirror_download_material_to_library(
                    result, "org-default", "node-1"
                ))

            self.assertEqual(persist_mock.call_count, 1)
            self.assertEqual(len(state["library"]), 1)
            self.assertEqual({item["id"] for item in results}, {old_id})
            self.assertTrue(self.validation.validate_video_file(str(old_path))["ok"])

    def test_central_new_mirror_rolls_back_state_when_persist_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "download"
            source.mkdir()
            make_test_video(source / "video.mp4")
            state = {"library": [], "nodes": {}}
            result = {
                "ok": True,
                "savePath": str(source),
                "material": {
                    "id": "remote-persist-failure-new",
                    "title": "new",
                    "type": "video",
                    "files": ["video.mp4"],
                    "sourceDownloadKey": "https://www.douyin.com/video/persist-failure-central-new",
                    "sourceDownloadPath": str(source),
                },
            }

            with mock.patch.object(self.central, "MATERIALS_DIR", str(root / "materials")), \
                    mock.patch.object(self.central, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.central, "STATE", state), \
                    mock.patch.object(self.central, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.central, "persist", side_effect=OSError("disk full")), \
                    mock.patch.object(self.central, "add_event", return_value=None):
                with self.assertRaisesRegex(OSError, "disk full"):
                    self.central.mirror_download_material_to_library(
                        result, "org-default", "node-1"
                    )

            self.assertEqual(state["library"], [])
            material_root = root / "materials"
            self.assertFalse(material_root.exists() and any(material_root.iterdir()))

    def test_central_repair_rolls_back_state_when_persist_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            source = root / "download"
            old_id = "central-persist-failure-repair"
            old_dir = materials / old_id
            old_dir.mkdir(parents=True)
            old_path = old_dir / "video.mp4"
            make_test_video(old_path, color="red")
            old_bytes = old_path.read_bytes()
            source.mkdir()
            make_test_video(source / "video.mp4")
            old = {
                "id": old_id,
                "orgId": "org-default",
                "title": "old",
                "type": "video",
                "files": ["video.mp4"],
                "published": 8,
                "createdAt": 444.0,
                "sourceDownloadKey": "https://www.douyin.com/video/persist-failure-central-repair",
                "remoteMaterialId": "remote-persist-failure-repair",
                "remoteNodeId": "node-1",
            }
            state = {"library": [old], "nodes": {}}
            result = {
                "ok": True,
                "savePath": str(source),
                "material": {
                    "id": old["remoteMaterialId"],
                    "title": "repaired",
                    "type": "video",
                    "files": ["video.mp4"],
                    "sourceDownloadKey": old["sourceDownloadKey"],
                    "sourceDownloadPath": str(source),
                },
            }
            original_validate = self.central.validate_video_file

            def force_repair(path):
                if os.path.normpath(path) == os.path.normpath(str(old_path)):
                    return {"ok": False, "code": "forced_repair"}
                return original_validate(path)

            with mock.patch.object(self.central, "MATERIALS_DIR", str(materials)), \
                    mock.patch.object(self.central, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.central, "STATE", state), \
                    mock.patch.object(self.central, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.central, "persist", side_effect=OSError("disk full")), \
                    mock.patch.object(self.central, "add_event", return_value=None), \
                    mock.patch.object(self.central, "validate_video_file", side_effect=force_repair):
                with self.assertRaisesRegex(OSError, "disk full"):
                    self.central.mirror_download_material_to_library(
                        result, "org-default", "node-1"
                    )

            self.assertEqual(state["library"], [old])
            self.assertEqual(old_path.read_bytes(), old_bytes)
            self.assertTrue(self.validation.validate_video_file(str(old_path))["ok"])
            self.assertTrue(list((root / "quarantine" / old_id).rglob("video.mp4")))
            self.assertTrue(list((root / "quarantine" / old_id).rglob("metadata.json")))

    def test_central_repair_metadata_failure_keeps_old_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            source = root / "download"
            old_id = "central-metadata-failure"
            old_dir = materials / old_id
            old_dir.mkdir(parents=True)
            old_path = old_dir / "video.mp4"
            make_test_video(old_path, color="red")
            old_bytes = old_path.read_bytes()
            source.mkdir()
            make_test_video(source / "video.mp4")
            old = {
                "id": old_id,
                "orgId": "org-default",
                "type": "video",
                "files": ["video.mp4"],
                "sourceDownloadKey": "central-metadata-failure",
                "remoteMaterialId": "remote-metadata-failure",
                "remoteNodeId": "node-1",
            }
            state = {"library": [old], "nodes": {}}
            result = {
                "ok": True,
                "savePath": str(source),
                "material": {
                    "id": old["remoteMaterialId"],
                    "type": "video",
                    "files": ["video.mp4"],
                    "sourceDownloadKey": old["sourceDownloadKey"],
                    "sourceDownloadPath": str(source),
                },
            }
            original_validate = self.central.validate_video_file
            original_replace = self.central.os.replace

            def force_repair(path):
                if os.path.normpath(path) == os.path.normpath(str(old_path)):
                    return {"ok": False, "code": "forced_repair"}
                return original_validate(path)

            def fail_metadata_commit(src, dst):
                if os.path.basename(dst) == "metadata.json":
                    raise OSError("metadata failed")
                return original_replace(src, dst)

            with mock.patch.object(self.central, "MATERIALS_DIR", str(materials)), \
                    mock.patch.object(self.central, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.central, "STATE", state), \
                    mock.patch.object(self.central, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.central, "persist", return_value=None), \
                    mock.patch.object(self.central, "add_event", return_value=None), \
                    mock.patch.object(self.central, "validate_video_file", side_effect=force_repair), \
                    mock.patch.object(self.central.os, "replace", side_effect=fail_metadata_commit):
                with self.assertRaisesRegex(OSError, "metadata failed"):
                    self.central.mirror_download_material_to_library(
                        result, "org-default", "node-1"
                    )

            self.assertEqual(state["library"], [old])
            self.assertEqual(old_path.read_bytes(), old_bytes)
            self.assertTrue(self.validation.validate_video_file(str(old_path))["ok"])

    def test_central_repair_quarantine_copy_failure_keeps_old_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            source = root / "download"
            old_id = "central-quarantine-copy-failure"
            old_dir = materials / old_id
            old_dir.mkdir(parents=True)
            old_path = old_dir / "video.mp4"
            make_test_video(old_path, color="red")
            old_bytes = old_path.read_bytes()
            source.mkdir()
            make_test_video(source / "video.mp4")
            old = {
                "id": old_id,
                "orgId": "org-default",
                "type": "video",
                "files": ["video.mp4"],
                "sourceDownloadKey": "central-copy-failure",
                "remoteMaterialId": "remote-copy-failure",
                "remoteNodeId": "node-1",
            }
            state = {"library": [old], "nodes": {}}
            result = {
                "ok": True,
                "savePath": str(source),
                "material": {
                    "id": old["remoteMaterialId"],
                    "type": "video",
                    "files": ["video.mp4"],
                    "sourceDownloadKey": old["sourceDownloadKey"],
                    "sourceDownloadPath": str(source),
                },
            }
            original_validate = self.central.validate_video_file
            original_copy = self.central.shutil.copy2

            def force_repair(path):
                if os.path.normpath(path) == os.path.normpath(str(old_path)):
                    return {"ok": False, "code": "forced_repair"}
                return original_validate(path)

            def fail_quarantine_copy(src, dst, *args, **kwargs):
                if os.path.normpath(str(root / "quarantine")) in os.path.normpath(dst):
                    raise OSError("quarantine copy failed")
                return original_copy(src, dst, *args, **kwargs)

            with mock.patch.object(self.central, "MATERIALS_DIR", str(materials)), \
                    mock.patch.object(self.central, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.central, "STATE", state), \
                    mock.patch.object(self.central, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.central, "persist", return_value=None), \
                    mock.patch.object(self.central, "add_event", return_value=None), \
                    mock.patch.object(self.central, "validate_video_file", side_effect=force_repair), \
                    mock.patch.object(self.central.shutil, "copy2", side_effect=fail_quarantine_copy):
                with self.assertRaisesRegex(OSError, "quarantine copy failed"):
                    self.central.mirror_download_material_to_library(
                        result, "org-default", "node-1"
                    )

            self.assertEqual(state["library"], [old])
            self.assertEqual(old_path.read_bytes(), old_bytes)
            self.assertTrue(self.validation.validate_video_file(str(old_path))["ok"])

    def test_central_repair_replace_failure_observes_old_file_in_place(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            source = root / "download"
            old_id = "central-replace-failure"
            old_dir = materials / old_id
            old_dir.mkdir(parents=True)
            old_path = old_dir / "video.mp4"
            make_test_video(old_path, color="red")
            old_bytes = old_path.read_bytes()
            source.mkdir()
            make_test_video(source / "video.mp4")
            old = {
                "id": old_id,
                "orgId": "org-default",
                "type": "video",
                "files": ["video.mp4"],
                "sourceDownloadKey": "central-replace-failure",
                "remoteMaterialId": "remote-replace-failure",
                "remoteNodeId": "node-1",
            }
            state = {"library": [old], "nodes": {}}
            result = {
                "ok": True,
                "savePath": str(source),
                "material": {
                    "id": old["remoteMaterialId"],
                    "type": "video",
                    "files": ["video.mp4"],
                    "sourceDownloadKey": old["sourceDownloadKey"],
                    "sourceDownloadPath": str(source),
                },
            }
            observed_old_in_place = []
            original_validate = self.central.validate_video_file
            original_replace = self.central.os.replace

            def force_repair(path):
                if os.path.normpath(path) == os.path.normpath(str(old_path)):
                    return {"ok": False, "code": "forced_repair"}
                return original_validate(path)

            def fail_candidate_replace(src, dst):
                if ".incoming-" in src and os.path.normpath(dst) == os.path.normpath(str(old_path)):
                    observed_old_in_place.append(old_path.is_file() and old_path.read_bytes() == old_bytes)
                    raise OSError("replace failed")
                return original_replace(src, dst)

            with mock.patch.object(self.central, "MATERIALS_DIR", str(materials)), \
                    mock.patch.object(self.central, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.central, "STATE", state), \
                    mock.patch.object(self.central, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.central, "persist", return_value=None), \
                    mock.patch.object(self.central, "add_event", return_value=None), \
                    mock.patch.object(self.central, "validate_video_file", side_effect=force_repair), \
                    mock.patch.object(self.central.os, "replace", side_effect=fail_candidate_replace):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    self.central.mirror_download_material_to_library(
                        result, "org-default", "node-1"
                    )

            self.assertEqual(observed_old_in_place, [True])
            self.assertEqual(state["library"], [old])
            self.assertEqual(old_path.read_bytes(), old_bytes)
            self.assertTrue(self.validation.validate_video_file(str(old_path))["ok"])

    def test_central_partial_replace_failure_restores_already_replaced_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            materials = root / "materials"
            source = root / "download"
            old_id = "central-partial-replace-failure"
            old_dir = materials / old_id
            old_dir.mkdir(parents=True)
            old_one = old_dir / "one.mp4"
            old_two = old_dir / "two.mp4"
            make_test_video(old_one, color="red")
            make_test_video(old_two, color="blue")
            old_one_bytes = old_one.read_bytes()
            old_two_bytes = old_two.read_bytes()
            source.mkdir()
            make_test_video(source / "one.mp4", color="green")
            make_test_video(source / "two.mp4", color="yellow")
            old = {
                "id": old_id,
                "orgId": "org-default",
                "type": "video",
                "files": ["one.mp4", "two.mp4"],
                "sourceDownloadKey": "central-partial-replace-failure",
                "remoteMaterialId": "remote-partial-replace-failure",
                "remoteNodeId": "node-1",
            }
            state = {"library": [old], "nodes": {}}
            result = {
                "ok": True,
                "savePath": str(source),
                "material": {
                    "id": old["remoteMaterialId"],
                    "type": "video",
                    "files": ["one.mp4", "two.mp4"],
                    "sourceDownloadKey": old["sourceDownloadKey"],
                    "sourceDownloadPath": str(source),
                },
            }
            original_validate = self.central.validate_video_file
            original_replace = self.central.os.replace

            def force_repair(path):
                if os.path.normpath(path) in {
                    os.path.normpath(str(old_one)),
                    os.path.normpath(str(old_two)),
                }:
                    return {"ok": False, "code": "forced_repair"}
                return original_validate(path)

            def fail_second_replace(src, dst):
                if ".incoming-" in src and os.path.normpath(dst) == os.path.normpath(str(old_two)):
                    raise OSError("second replace failed")
                return original_replace(src, dst)

            with mock.patch.object(self.central, "MATERIALS_DIR", str(materials)), \
                    mock.patch.object(self.central, "MATERIAL_QUARANTINE_DIR", str(root / "quarantine")), \
                    mock.patch.object(self.central, "STATE", state), \
                    mock.patch.object(self.central, "cleanup_quarantine", return_value=None), \
                    mock.patch.object(self.central, "persist", return_value=None), \
                    mock.patch.object(self.central, "add_event", return_value=None), \
                    mock.patch.object(self.central, "validate_video_file", side_effect=force_repair), \
                    mock.patch.object(self.central.os, "replace", side_effect=fail_second_replace):
                with self.assertRaisesRegex(OSError, "second replace failed"):
                    self.central.mirror_download_material_to_library(
                        result, "org-default", "node-1"
                    )

            self.assertEqual(state["library"], [old])
            self.assertEqual(old_one.read_bytes(), old_one_bytes)
            self.assertEqual(old_two.read_bytes(), old_two_bytes)
            self.assertTrue(self.validation.validate_video_file(str(old_one))["ok"])
            self.assertTrue(self.validation.validate_video_file(str(old_two))["ok"])


if __name__ == "__main__":
    unittest.main()
