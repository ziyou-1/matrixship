from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
ALLOWED_NEGATIONS = {
    "!.env.example",
    "!**/.env.example",
}


def load_dockerignore_patterns(path):
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def load_ignore_patterns(path):
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def disallowed_negations(patterns):
    return [
        pattern
        for pattern in patterns
        if pattern.startswith("!") and pattern not in ALLOWED_NEGATIONS
    ]


class DeploymentSecurityTest(unittest.TestCase):
    def test_dockerignore_excludes_sensitive_and_runtime_data(self):
        dockerignore = BACKEND / ".dockerignore"
        self.assertTrue(dockerignore.exists(), "backend/.dockerignore is missing")

        lines = load_dockerignore_patterns(dockerignore)
        required_patterns = {
            ".env",
            ".env.*",
            "!.env.example",
            "__pycache__/",
            "*.pyc",
            "*.log",
            ".pytest_cache/",
            "central_data/",
            "datas/",
            "uploads/",
            "user_data/",
            "backups/",
            "*.bak",
        }

        self.assertTrue(
            required_patterns.issubset(lines),
            f"missing .dockerignore patterns: {sorted(required_patterns - set(lines))}",
        )
        self.assertGreater(lines.index("!.env.example"), lines.index(".env.*"))

    def test_dockerignore_rejects_unapproved_negation_rules(self):
        patterns = load_dockerignore_patterns(BACKEND / ".dockerignore")

        self.assertEqual([], disallowed_negations(patterns))

    def test_negation_allowlist_rejects_globs_character_classes_and_paths(self):
        rejected_rules = (
            "!central_data/",
            "!.env.production",
            "!central_data/[a-z]*.json",
            "!**/uploads/**",
        )

        for rule in rejected_rules:
            with self.subTest(rule=rule):
                self.assertEqual([rule], disallowed_negations([rule]))
        self.assertEqual([], disallowed_negations(sorted(ALLOWED_NEGATIONS)))

    def test_copy_all_dockerfile_has_dockerignore_guard(self):
        dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("COPY . .", dockerfile)
        self.assertTrue((BACKEND / ".dockerignore").exists())

    def test_backend_dockerfile_has_production_healthcheck(self):
        dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn("/api/health", dockerfile)
        self.assertIn("central_server.py", dockerfile)
        self.assertIn("CENTRAL_PORT", dockerfile)

    def test_root_prod_compose_defines_central_service(self):
        compose = ROOT / "docker-compose.prod.yml"
        self.assertTrue(compose.exists(), "docker-compose.prod.yml is missing")
        text = compose.read_text(encoding="utf-8")

        for required in (
            "matrix-central:",
            "build:",
            "context: ./backend",
            "env_file:",
            ".env.prod",
            "healthcheck:",
            "/api/health",
            "restart: unless-stopped",
            "CENTRAL_DATA_DIR",
        ):
            self.assertIn(required, text)

    def test_gitignore_excludes_sensitive_runtime_and_local_validation_data(self):
        gitignore = ROOT / ".gitignore"
        self.assertTrue(gitignore.exists(), ".gitignore is missing")

        lines = load_ignore_patterns(gitignore)
        required_patterns = {
            ".env",
            ".env.*",
            "!.env.example",
            ".venv/",
            ".venv-win/",
            ".tmp-validation/",
            ".playwright-cli/",
            ".workbuddy/",
            "node_modules/",
            "logs/",
            "*.log",
            ".tmp-*.log",
            ".tmp-*.txt",
            ".tmp-*.json",
            ".tmp-*.cmd",
            ".tmp-*.ps1",
            "tmp_*.log",
            "tmp_*.mp4",
            "tmp_*/",
            "backend/central_data/",
            "backend/datas/",
            "backend/uploads/",
            "tools/cloudflared",
            "tools/cloudflared.tgz",
            "backups/",
            "__pycache__/",
            "**/__pycache__/",
            "*.pyc",
            ".DS_Store",
            "Thumbs.db",
        }

        self.assertTrue(
            required_patterns.issubset(lines),
            f"missing .gitignore patterns: {sorted(required_patterns - set(lines))}",
        )

    def test_gitignore_keeps_remote_server_mirrors_visible_but_ignores_scratch_scripts(self):
        lines = load_ignore_patterns(ROOT / ".gitignore")
        required_patterns = {
            ".tmp-known-hosts",
            ".tmp-aicanvas-ai-api-service.py",
            ".tmp-aicanvas-server-current.py",
            ".tmp-aicanvas-server.py",
            ".tmp-aicanvas-test-*.py",
            ".tmp-platform-*.py",
            ".tmp-platform-test-*.py",
            ".tmp-real-comic-e2e*.py",
            ".tmp-run-prepared-comic-e2e*.py",
            ".tmp-resume-real-comic-e2e.py",
            ".tmp-recover-comic-task.py",
            ".tmp-remote-aicanvas-ops.py",
        }

        self.assertTrue(
            required_patterns.issubset(lines),
            f"missing scratch ignore patterns: {sorted(required_patterns - set(lines))}",
        )
        self.assertNotIn(".tmp-*.py", lines)

    def test_git_boundary_document_defines_source_and_scratch_surfaces(self):
        doc = ROOT / "docs" / "GIT_BOUNDARY.md"
        self.assertTrue(doc.exists(), "docs/GIT_BOUNDARY.md is missing")
        text = doc.read_text(encoding="utf-8")

        for required in (
            "Tracked source surfaces",
            "Ignored local surfaces",
            "Remote AI Canvas mirrors",
            "tools/aicanvas_remote/server_current.py",
            "tools/aicanvas_remote/server_legacy.py",
            "backend/",
            "docs/",
            "tests/",
            ".tmp-validation/",
        ):
            self.assertIn(required, text)

    def test_remote_aicanvas_server_mirrors_use_stable_source_paths(self):
        current = ROOT / "tools" / "aicanvas_remote" / "server_current.py"
        legacy = ROOT / "tools" / "aicanvas_remote" / "server_legacy.py"

        self.assertTrue(current.exists(), "current AI Canvas mirror is missing")
        self.assertTrue(legacy.exists(), "legacy AI Canvas mirror is missing")
        self.assertFalse((ROOT / ".tmp-aicanvas-server-current.py").exists())
        self.assertFalse((ROOT / ".tmp-aicanvas-server.py").exists())

    def test_git_tracking_manifest_lists_stage_and_hold_surfaces(self):
        manifest = ROOT / "docs" / "GIT_TRACKING_MANIFEST.md"
        self.assertTrue(manifest.exists(), "docs/GIT_TRACKING_MANIFEST.md is missing")
        text = manifest.read_text(encoding="utf-8")

        for required in (
            "Must stage as source",
            "Remote AI Canvas mirrors",
            "Not staged without migration",
            ".gitignore",
            "backend/api_server.py",
            "backend/central_server.py",
            "backend/matrix_native_client.py",
            "docs/openapi.yaml",
            "tests/test_deployment_security.py",
            "tools/aicanvas_remote/server_current.py",
            "tools/aicanvas_remote/server_legacy.py",
            "tools/cloudflared",
            "tools/cloudflared.tgz",
        ):
            self.assertIn(required, text)

    def test_windows_start_script_uses_project_python312_venv(self):
        script = (ROOT / "start-local-test.ps1").read_text(encoding="utf-8")

        self.assertIn(".venv-win", script)
        self.assertIn("Scripts\\python.exe", script)
        self.assertIn("$PSScriptRoot", script)
        self.assertNotIn("Start-Process python", script)


if __name__ == "__main__":
    unittest.main()
