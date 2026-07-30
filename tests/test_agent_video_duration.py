from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


class AgentVideoDurationTest(unittest.TestCase):
    def test_agent_video_duration_is_selectable(self):
        source = CLIENT.read_text(encoding="utf-8-sig")

        self.assertIn("AGENT_VIDEO_DURATIONS = (5, 10)", source)
        self.assertIn("self.b_duration = _icon_text_btn", source)
        self.assertIn("def _cycle_video_duration(self):", source)
        self.assertIn('"duration": self._current_video_duration()', source)
        self.assertIn("dur = _agent_video_duration(entry.get(\"duration\"))", source)
        self.assertNotIn("dur = 5\n    model =", source)


if __name__ == "__main__":
    unittest.main()
