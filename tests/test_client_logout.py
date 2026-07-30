import importlib.util
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "backend" / "matrix_native_client.py"


def load_client():
    spec = importlib.util.spec_from_file_location("matrix_native_client_for_logout", CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ClientLogoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_client()

    def test_restart_client_uses_qt_detached_process(self):
        with mock.patch.object(
            self.client.QtCore.QProcess,
            "startDetached",
            return_value=(True, 4321),
        ) as start_detached, mock.patch.object(self.client, "json_log") as write_log:
            ok, error_id = self.client._restart_client_detached()

        self.assertTrue(ok)
        self.assertEqual(error_id, "")
        program, arguments, cwd = start_detached.call_args.args
        self.assertEqual(program, self.client.sys.executable)
        self.assertEqual(arguments, [str(CLIENT)])
        self.assertEqual(cwd, str(CLIENT.parent))
        write_log.assert_called_once()
        self.assertEqual(write_log.call_args.args[1], "client_logout_restart_started")

    def test_restart_failure_returns_traceable_error(self):
        with mock.patch.object(
            self.client.QtCore.QProcess,
            "startDetached",
            return_value=(False, 0),
        ), mock.patch.object(self.client, "json_log") as write_log:
            ok, error_id = self.client._restart_client_detached()

        self.assertFalse(ok)
        self.assertTrue(error_id.startswith("err-"))
        write_log.assert_called_once()
        self.assertEqual(write_log.call_args.args[1], "client_logout_restart_failed")
        self.assertEqual(write_log.call_args.kwargs["errorId"], error_id)


if __name__ == "__main__":
    unittest.main()
