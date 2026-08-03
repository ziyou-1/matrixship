from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "start-visible-client.bat"


class StartVisibleClientScriptTest(unittest.TestCase):
    def test_start_script_restarts_existing_central_before_health_check(self):
        source = SCRIPT.read_text(encoding="utf-8")
        lower = source.lower()

        self.assertIn("call :restart_central", lower)
        self.assertLess(lower.index("call :restart_central"), lower.index("call :check_central"))
        self.assertRegex(lower, r":restart_central[\s\S]+netstat -ano")
        self.assertRegex(lower, r":restart_central[\s\S]+taskkill /f /pid")
        self.assertRegex(lower, r":restart_central[\s\S]+:%central_port%")

    def test_start_script_restarts_existing_local_executor_before_client(self):
        source = SCRIPT.read_text(encoding="utf-8")
        lower = source.lower()

        self.assertIn('set "local_api_port=9081"', lower)
        self.assertIn("call :restart_local_executor", lower)
        self.assertLess(lower.index("call :restart_local_executor"), lower.index("starting matrixship client"))
        self.assertRegex(lower, r":restart_local_executor[\s\S]+netstat -ano")
        self.assertRegex(lower, r":restart_local_executor[\s\S]+taskkill /f /pid")
        self.assertRegex(lower, r":restart_local_executor[\s\S]+:%local_api_port%")


if __name__ == "__main__":
    unittest.main()
