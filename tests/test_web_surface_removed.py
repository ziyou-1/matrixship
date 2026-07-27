from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


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

    def test_build_stays_native_only(self):
        build = (ROOT / "backend" / "build_matrix_agent.ps1").read_text(encoding="utf-8")
        installer = (ROOT / "backend" / "installer" / "MatrixShipAgent.iss").read_text(encoding="utf-8")
        self.assertNotIn("frontend\\downloads", build)
        self.assertNotIn("frontend\\downloads", installer)
        self.assertIn("dist\\installer\\MatrixShipAgent-Setup.exe", build)


if __name__ == "__main__":
    unittest.main()
