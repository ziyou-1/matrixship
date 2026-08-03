import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class DouyinMultiAccountTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = importlib.import_module("api_server")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.old_env = os.environ.copy()
        self.api.DATA_DIR = str(self.data_dir)
        self.api.DOUYIN_ACCOUNTS_JSON = str(self.data_dir / "douyin_accounts.json")
        self.api.DOUYIN_ACCOUNT_PROFILES_DIR = str(self.data_dir / "douyin_accounts")
        self.api.AUTH_CACHE_JSON = str(self.data_dir / "auth_cookie.json")
        os.environ["DY_PROFILE_DIR"] = str(self.data_dir / "dy_profile")
        with self.api.STATE_LOCK:
            self.api.STATE["auth"] = self.api.DouyinAuth()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)
        self.tmp.cleanup()

    def test_registers_multiple_douyin_accounts_without_overwriting_profiles(self):
        first_profile = self.data_dir / "first_profile"
        second_profile = self.data_dir / "second_profile"
        first_profile.mkdir()
        second_profile.mkdir()
        (first_profile / "marker.txt").write_text("first", encoding="utf-8")
        (second_profile / "marker.txt").write_text("second", encoding="utf-8")

        first = self.api.register_douyin_account(
            "sessionid=first-session; uid_tt=uid-first; LOGIN_STATUS=1",
            profile_dir=str(first_profile),
            source="test",
        )
        second = self.api.register_douyin_account(
            "sessionid=second-session; uid_tt=uid-second; LOGIN_STATUS=1",
            profile_dir=str(second_profile),
            source="test",
        )

        self.assertNotEqual(first["id"], second["id"])
        accounts = [a for a in self.api.current_accounts() if a.get("platform") == "douyin"]
        ids = {a["id"] for a in accounts}
        self.assertIn(first["id"], ids)
        self.assertIn(second["id"], ids)
        self.assertTrue(Path(first["profileDir"], "marker.txt").exists())
        self.assertTrue(Path(second["profileDir"], "marker.txt").exists())

    def test_current_accounts_hides_default_douyin_placeholder_without_login_cookie(self):
        accounts = [a for a in self.api.current_accounts() if a.get("platform") == "douyin"]

        self.assertEqual(accounts, [])

    def test_load_douyin_accounts_recovers_from_profile_dirs_when_registry_json_is_corrupt(self):
        account_dir = self.data_dir / "douyin_accounts" / "douyin-recovered123456"
        profile_dir = account_dir / "dy_profile"
        profile_dir.mkdir(parents=True)
        (account_dir / "auth_cookie.json").write_text(
            json.dumps({"cookie": "sessionid=recovered-session", "hasLoginCookie": True, "savedAt": 123.0}),
            encoding="utf-8",
        )
        Path(self.api.DOUYIN_ACCOUNTS_JSON).write_text('[{"id":"broken","name":"bad]', encoding="utf-8")

        rows = self.api.load_douyin_accounts()

        self.assertEqual([r["id"] for r in rows], ["douyin-recovered123456"])
        self.assertEqual(rows[0]["profileDir"], str(profile_dir))
        self.assertTrue(Path(self.api.DOUYIN_ACCOUNTS_JSON).with_suffix(".json.invalid").exists())

    def test_publish_uses_selected_account_cookie_and_profile(self):
        profile = self.data_dir / "selected_profile"
        profile.mkdir()
        account = self.api.register_douyin_account(
            "sessionid=selected-session; uid_tt=uid-selected; LOGIN_STATUS=1",
            profile_dir=str(profile),
            source="test",
        )

        material = {"id": "mat-1", "title": "title", "type": "video"}
        video_path = str(self.data_dir / "video.mp4")
        Path(video_path).write_bytes(b"fake")

        observed = {}

        def fake_publish(cookie, files, title, kind, dry_run=True):
            observed["cookie"] = dict(cookie)
            observed["profile"] = os.environ.get("DY_PROFILE_DIR")
            return {"ok": True, "published": True}

        with mock.patch.object(self.api, "material_files", return_value=[video_path]), \
                mock.patch.object(self.api, "publish_to_douyin", side_effect=fake_publish), \
                mock.patch.object(self.api, "bump_published", return_value=None):
            result = self.api.run_publish(material, account["id"], dry_run=True)

        self.assertTrue(result["ok"])
        self.assertEqual(observed["cookie"].get("sessionid"), "selected-session")
        self.assertEqual(os.path.abspath(observed["profile"]), os.path.abspath(account["profileDir"]))

    def test_douyin_publish_blocks_multi_file_material_before_browser_upload(self):
        profile = self.data_dir / "selected_profile"
        profile.mkdir()
        account = self.api.register_douyin_account(
            "sessionid=selected-session; uid_tt=uid-selected; LOGIN_STATUS=1",
            profile_dir=str(profile),
            source="test",
        )
        material = {"id": "mat-1", "title": "title", "type": "video"}
        video_paths = [str(self.data_dir / "first.mp4"), str(self.data_dir / "second.mp4")]
        for video_path in video_paths:
            Path(video_path).write_bytes(b"fake")

        with mock.patch.object(self.api, "material_files", return_value=video_paths), \
                mock.patch.object(self.api, "publish_to_douyin") as publish_mock:
            result = self.api.run_publish(material, account["id"], dry_run=False, platform="douyin")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "douyin_single_video_required")
        self.assertEqual(result["fileCount"], 2)
        publish_mock.assert_not_called()

    def test_require_auth_rejects_ms_token_only_cookie(self):
        auth = self.api.DouyinAuth()
        auth.perepare_auth("msToken=generated-only")
        with self.api.STATE_LOCK:
            self.api.STATE["auth"] = auth

        with self.assertRaisesRegex(RuntimeError, "douyin_auth_incomplete"):
            self.api.require_auth()

    def test_comment_read_defaults_to_latest_usable_douyin_account(self):
        profile = self.data_dir / "comment_profile"
        profile.mkdir()
        account = self.api.register_douyin_account(
            "sessionid=selected-session; uid_tt=uid-selected; s_v_web_id=fingerprint; LOGIN_STATUS=1",
            profile_dir=str(profile),
            source="test",
        )
        self.api.save_cookie_cache("msToken=default-only", source="test-default")
        default_auth = self.api.DouyinAuth()
        default_auth.perepare_auth("msToken=default-only")
        with self.api.STATE_LOCK:
            self.api.STATE["auth"] = default_auth

        selected = self.api.default_douyin_comment_account_id()

        self.assertEqual(selected, account["id"])
        with self.api.douyin_account_scope(selected) as (auth, _paths):
            self.assertEqual(auth.cookie.get("sessionid"), "selected-session")

    def test_account_rename_persists_display_name_without_cookie_leak(self):
        profile = self.data_dir / "rename_profile"
        profile.mkdir()
        account = self.api.register_douyin_account(
            "sessionid=rename-session; uid_tt=uid-rename; LOGIN_STATUS=1",
            profile_dir=str(profile),
            source="test",
        )

        result = self.api.rename_account_display_name(account["id"], "123")

        self.assertTrue(result["ok"])
        self.assertEqual(result["id"], account["id"])
        accounts = [a for a in self.api.current_accounts() if a.get("id") == account["id"]]
        self.assertEqual(accounts[0]["name"], "123")
        self.assertEqual(accounts[0]["nickname"], "123")
        self.assertNotIn("cookie", json.dumps(result))

    def test_remove_xhs_account_hides_saved_profile_until_relogin(self):
        materials_dir = self.data_dir / "materials"
        materials_dir.mkdir(parents=True, exist_ok=True)
        material_marker = materials_dir / "keep.txt"
        material_marker.write_text("keep", encoding="utf-8")
        xhs_profile = self.data_dir / "xhs_profile"
        xhs_profile.mkdir(parents=True, exist_ok=True)
        profile_marker = xhs_profile / "profile.txt"
        profile_marker.write_text("profile", encoding="utf-8")
        cookie_file = xhs_profile / "Default" / "Network" / "Cookies"
        cookie_file.parent.mkdir(parents=True, exist_ok=True)
        cookie_file.write_text("cookie-db", encoding="utf-8")
        self.api._save_json(str(self.data_dir / "xhs_auth_state.json"), {
            "loggedIn": True,
            "cookieCount": 2,
            "profileDir": str(xhs_profile),
        })

        result = self.api.remove_local_account("xhs-self")

        self.assertTrue(result["ok"])
        self.assertEqual(result["id"], "xhs-self")
        self.assertFalse((self.data_dir / "xhs_auth_state.json").exists())
        self.assertFalse(cookie_file.exists())
        self.assertTrue(profile_marker.exists())
        self.assertTrue(material_marker.exists())

    def test_remove_default_douyin_account_hides_saved_auth_until_relogin(self):
        self.api.save_cookie_cache(
            "sessionid=default-session; uid_tt=uid-default; LOGIN_STATUS=1",
            source="test-default",
        )
        default_auth = self.api.DouyinAuth()
        default_auth.perepare_auth("sessionid=default-session; uid_tt=uid-default; LOGIN_STATUS=1")
        with self.api.STATE_LOCK:
            self.api.STATE["auth"] = default_auth
        before = [a for a in self.api.current_accounts() if a.get("id") == "douyin-self"]
        self.assertEqual(len(before), 1)

        result = self.api.remove_local_account("douyin-self")

        self.assertTrue(result["ok"])
        self.assertEqual(result["id"], "douyin-self")
        after = [a for a in self.api.current_accounts() if a.get("platform") == "douyin"]
        self.assertEqual(after, [])

        self.api.set_auth_from_cookie(
            "sessionid=relogin-session; uid_tt=uid-relogin; LOGIN_STATUS=1",
            source="manual",
            persist=True,
        )
        restored = [a for a in self.api.current_accounts() if a.get("id") == "douyin-self"]
        self.assertEqual(len(restored), 1)

    def test_finder_discover_defaults_to_latest_usable_douyin_account(self):
        profile = self.data_dir / "finder_profile"
        profile.mkdir()
        account = self.api.register_douyin_account(
            "sessionid=finder-session; uid_tt=uid-finder; s_v_web_id=fingerprint; LOGIN_STATUS=1",
            profile_dir=str(profile),
            source="test",
        )
        self.api.save_cookie_cache("msToken=default-only", source="test-default")
        default_auth = self.api.DouyinAuth()
        default_auth.perepare_auth("msToken=default-only")
        with self.api.STATE_LOCK:
            self.api.STATE["auth"] = default_auth

        observed = {}

        def fake_discover(platform, auth, keyword, video_num, comment_mode):
            observed["platform"] = platform
            observed["sessionid"] = auth.cookie.get("sessionid")
            observed["profile"] = os.environ.get("DY_PROFILE_DIR")
            return {"keyword": keyword, "platform": platform, "videos": [], "comments": [], "leads": []}

        class FakeHandler:
            path = "/api/finder/discover"
            headers = {"Content-Type": "application/json"}

            def __init__(self):
                body = {"platform": "douyin", "keyword": "keyword", "videoNum": 1, "commentMode": "page"}
                self.rfile = io.BytesIO(json.dumps(body).encode("utf-8"))
                self.headers = {
                    "Content-Type": "application/json",
                    "Content-Length": str(len(self.rfile.getvalue())),
                }
                self.wfile = io.BytesIO()
                self.status = None

            def send_response(self, status):
                self.status = status

            def send_header(self, _name, _value):
                pass

            def end_headers(self):
                pass

        handler = FakeHandler()
        with mock.patch.dict(os.environ, {"MATRIX_AGENT_TOKEN_AUTH": "0"}), \
                mock.patch.object(self.api, "discover_leads_by_keyword_platform", side_effect=fake_discover):
            self.api.Handler.do_POST(handler)

        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(handler.status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(observed["sessionid"], "finder-session")
        self.assertEqual(os.path.abspath(observed["profile"]), os.path.abspath(account["profileDir"]))


if __name__ == "__main__":
    unittest.main()
