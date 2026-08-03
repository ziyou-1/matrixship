from pathlib import Path
import importlib
import io
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class WebSurfaceRemovedTest(unittest.TestCase):
    def test_product_web_files_are_absent(self):
        for relative in (
            "frontend",
            "backend/admin_console.html",
            "backend/tools/dev_proxy.py",
            "backend/LOCAL_AGENT_COMMERCIAL.md",
            "backend/SCHEME3_CLOUD_NODES.md",
            "tests/test_web_login_navigation.py",
            "docs/superpowers/specs/2026-07-18-web-interaction-usability-design.md",
        ):
            with self.subTest(path=relative):
                self.assertFalse((ROOT / relative).exists())

    def test_no_active_product_html_remains(self):
        excluded = {"backups", "node_modules", ".git", ".playwright-cli", ".tmp-validation"}
        html = [
            path for path in ROOT.rglob("*.html")
            if not excluded.intersection(path.relative_to(ROOT).parts)
            and path.relative_to(ROOT).parts[0] not in {".venv", ".venv-win"}
            and path.relative_to(ROOT).parts[:2] != ("backend", "datas")
        ]
        self.assertEqual(html, [])

    def test_center_no_longer_serves_admin_or_frontend_installer_path(self):
        source = (ROOT / "backend" / "central_server.py").read_text(encoding="utf-8")
        self.assertNotIn("admin_console.html", source)
        self.assertNotIn('path == "/admin"', source)
        self.assertNotIn('"frontend", "downloads"', source)
        self.assertIn("def serve_agent_installer", source)
        self.assertIn("MATRIXSHIP_AGENT_INSTALLER", source)
        self.assertIn('path == "/MatrixShipAgent-Setup.exe"', source)

    def test_center_serves_public_download_page_contract(self):
        central = importlib.import_module("central_server")
        html = central.Handler.download_page_html()

        self.assertIn("云灵星图 AI 爆款复刻平台 Windows 客户端下载", html)
        self.assertIn("云灵星图数字科技有限公司", html)
        self.assertIn("Windows 客户端即将开放下载", html)
        self.assertIn("disabled", html)
        self.assertNotIn("/MatrixShipAgent-Setup.exe", html)

    def test_download_page_response_is_public_html(self):
        central = importlib.import_module("central_server")
        handler = object.__new__(central.Handler)
        handler.wfile = io.BytesIO()
        handler.headers = {}
        sent = []

        def send_response(status):
            sent.append(("status", status))

        def send_header(name, value):
            sent.append(("header", name, value))

        handler.send_response = send_response
        handler.send_header = send_header
        handler.end_headers = lambda: sent.append(("end",))

        central.Handler.serve_download_page(handler)

        body = handler.wfile.getvalue().decode("utf-8")
        self.assertIn(("status", 200), sent)
        self.assertIn(("header", "Content-Type", "text/html; charset=utf-8"), sent)
        self.assertIn("云灵星图 AI 爆款复刻平台 Windows 客户端下载", body)
        self.assertIn("Windows 客户端即将开放下载", body)
        self.assertNotIn("/MatrixShipAgent-Setup.exe", body)

    def test_download_route_is_public_before_auth_gate(self):
        source = (ROOT / "backend" / "central_server.py").read_text(encoding="utf-8")
        route_index = source.index('if path == "/download":')
        auth_index = source.index("if not require_user(self):", route_index)

        self.assertLess(route_index, auth_index)
        self.assertIn("return self.serve_download_page()", source[route_index:auth_index])

    def test_build_stays_native_only(self):
        build = (ROOT / "backend" / "build_matrix_agent.ps1").read_text(encoding="utf-8")
        installer = (ROOT / "backend" / "installer" / "MatrixShipAgent.iss").read_text(encoding="utf-8")
        self.assertNotIn("frontend\\downloads", build)
        self.assertNotIn("frontend\\downloads", installer)
        self.assertIn("dist\\installer\\MatrixShipAgent-Setup.exe", build)


if __name__ == "__main__":
    unittest.main()
