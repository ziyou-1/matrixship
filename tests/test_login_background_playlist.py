from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


class LoginBackgroundPlaylistTest(unittest.TestCase):
    def test_login_background_uses_only_requested_videos_with_liquid_first(self):
        src = CLIENT.read_text(encoding="utf-8")
        playlist = src[src.index("    def _playlist(self):"):src.index("    def _init_player(self):")]

        expected = ["gen-liquid-lo.mp4", "car.mp4", "ecom-serum-lo.mp4", "phone.mp4"]
        filenames = re.findall(r'"([^"]+\.mp4)"', playlist)
        self.assertEqual(expected, filenames)
        self.assertNotIn("gen-cosmetic-lo.mp4", playlist)
        self.assertNotIn("os.listdir", playlist)
        self.assertNotIn("endswith(\"-lo.mp4\")", playlist)

    def test_login_background_does_not_loop_each_video_indefinitely(self):
        src = CLIENT.read_text(encoding="utf-8")
        login_bg = src[src.index("class LoginBackground"):src.index("class LoginView")]

        self.assertNotIn("QMediaPlayer.Loops.Infinite", login_bg)
        self.assertIn("self.player.setLoops(1)", login_bg)
        self.assertIn("mediaStatusChanged.connect(self._on_media_status)", login_bg)
        self.assertIn("QMediaPlayer.MediaStatus.EndOfMedia", login_bg)


if __name__ == "__main__":
    unittest.main()
