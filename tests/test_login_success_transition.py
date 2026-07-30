from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


class LoginSuccessTransitionTest(unittest.TestCase):
    def test_login_success_no_longer_uses_evil_eye_transition(self):
        src = CLIENT.read_text(encoding="utf-8")
        login_view = src[src.index("class LoginView"):src.index("\n\nclass MainWindow")]

        self.assertNotIn("EVIL_EYE_LOGIN_PATH", src)
        self.assertNotIn("evil_eye_login.png", src)
        self.assertNotIn("LOGIN_SUCCESS_TRANSITION_MS", login_view)
        self.assertNotIn("LOGIN_SUCCESS_FULL_SCREEN_SCALE", login_view)
        self.assertNotIn("_build_success_overlay", login_view)
        self.assertNotIn("_play_success_transition", login_view)
        self.assertNotIn("_finish_success_transition", login_view)
        self.assertNotIn("_success_overlay", login_view)
        self.assertNotIn("QParallelAnimationGroup", login_view)

    def test_login_success_enters_main_app_immediately_after_releasing_background(self):
        src = CLIENT.read_text(encoding="utf-8")
        done = src[src.index("    def _done(self, ok, info):"):src.index("\n\nclass MainWindow")]

        ok_block = done[done.index("        if ok:"):]
        self.assertIn("self.bg.release()", ok_block)
        self.assertIn("self.on_success(info)", ok_block)
        self.assertLess(ok_block.index("self.bg.release()"), ok_block.index("self.on_success(info)"))
        self.assertNotIn("_play_success_transition", ok_block)

    def test_login_failure_path_is_unchanged(self):
        src = CLIENT.read_text(encoding="utf-8")
        done = src[src.index("    def _done(self, ok, info):"):src.index("\n\nclass MainWindow")]

        failure_prefix = done[:done.index("        if ok:")]
        self.assertIn('("登录失败:" + message)', failure_prefix)
        self.assertNotIn("self.bg.release()", failure_prefix)
        self.assertNotIn("self.on_success(info)", failure_prefix)


if __name__ == "__main__":
    unittest.main()
