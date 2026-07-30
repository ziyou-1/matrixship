from pathlib import Path
import importlib.util
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "backend" / "central_server.py"


def load_server_module():
    spec = importlib.util.spec_from_file_location("central_server_under_test", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LibraryVideoPlaybackTest(unittest.TestCase):
    def test_material_file_range_parser_supports_browser_video_requests(self):
        server = load_server_module()
        parse = server.parse_http_range
        self.assertEqual(parse("bytes=0-3", 10), (0, 3))
        self.assertEqual(parse("bytes=5-", 10), (5, 9))
        self.assertEqual(parse("bytes=-4", 10), (6, 9))
        self.assertIsNone(parse("items=0-3", 10))
        self.assertIsNone(parse("bytes=20-30", 10))


if __name__ == "__main__":
    unittest.main()
