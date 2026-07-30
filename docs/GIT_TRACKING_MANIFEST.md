# Git Tracking Manifest

This manifest is the staging checklist for turning the current workspace into a
reviewable repository state. It does not authorize deletion, movement, staging,
or commit by itself.

## Must stage as source

Stage these when preparing the formal source snapshot, after reviewing their
current contents and excluding credentials or runtime data:

- Git and boundary controls: `.gitignore`, `docs/GIT_BOUNDARY.md`,
  `docs/GIT_TRACKING_MANIFEST.md`, and
  `tests/test_deployment_security.py`.
- Release and operator documents: `CHANGELOG.md`, `LOCAL_TEST.md`,
  `MIGRATION.md`, `migration.sql`, `docker-compose.prod.yml`,
  `docs/ARCHITECTURE.md`, `docs/API_REFERENCE.md`,
  `docs/DEPLOYMENT.md`, `docs/IMPLEMENTATION.md`,
  `docs/TROUBLESHOOTING.md`, `docs/openapi.yaml`, and
  `docs/sdd_progress.md`.
- Planning records that explain current behavior: `docs/superpowers/plans/`
  and `docs/superpowers/specs/`.
- Backend source and deploy assets: `backend/.dockerignore`,
  `backend/.env.example`, `backend/.gitignore`, `backend/Dockerfile`,
  `backend/README.md`, `backend/ENTERPRISE_DEVELOPMENT_PLAN.md`,
  `backend/agent_worker.py`, `backend/api_server.py`,
  `backend/billing_analytics.py`, `backend/central_server.py`,
  `backend/creator_login.py`, `backend/edge_ui_comment.py`,
  `backend/install_matrix_agent.ps1`,
  `backend/local_browser_worker.py`, `backend/local_login.py`,
  `backend/main.py`, `backend/maindb.py`,
  `backend/matrix_native_client.py`, `backend/matrix_sso.py`,
  `backend/package-lock.json`, `backend/package.json`,
  `backend/platform_adapters.py`, `backend/requirements.deploy.txt`,
  `backend/requirements.txt`, `backend/runtime_paths.py`,
  `backend/send_comment.py`, `backend/sign_selftest.py`,
  `backend/start-central-server.bat`, `backend/start-exec-node.bat`,
  `backend/start-matrix-agent.bat`, `backend/validate_douyin_flow.py`,
  and `backend/xhs_note_replacement.py`.
- Backend source directories: `backend/assets/`, `backend/author/`,
  `backend/builder/`, `backend/dy_apis/`, `backend/dy_live/`,
  `backend/installer/`, `backend/legal/`, `backend/migrations/`,
  `backend/static/`, `backend/tools/`, and `backend/utils/`.
- Tests: `tests/`, including `tests/test_deployment_security.py`.
- Operator scripts and shell helpers: `scripts/`, `bin/`,
  `start-local-test.ps1`, and `start-visible-client.bat`.
- Source tools: `tools/repair_scheduler_state.py`,
  `tools/aicanvas_remote/server_current.py`, and
  `tools/aicanvas_remote/server_legacy.py`.

## Remote AI Canvas mirrors

These are formal source mirrors of remote service files. Stage them when changed
with focused tests, deployment notes, backup hash, and rollback path:

- `tools/aicanvas_remote/server_current.py`
- `tools/aicanvas_remote/server_legacy.py`

## Not staged without migration

Do not stage these as source in their current form. They are downloaded local
tool artifacts and should stay ignored unless a later change replaces them with
a documented installer, checksum, or pinned package source:

- `tools/cloudflared`
- `tools/cloudflared.tgz`

## Review gates before staging

1. Run `git status --short --ignored` and confirm ignored files are only local
   runtime, dependency, cache, validation, credential, or downloaded artifacts.
2. Review every source candidate for secrets before staging.
3. Keep remote AI Canvas mirrors under `tools/aicanvas_remote/`; do not create
   new root `.tmp-aicanvas-server*.py` source mirrors.
4. Do not stage modified tracked files from unrelated feature work unless the
   release scope explicitly includes them.
5. Re-run `tests.test_deployment_security` after any change to `.gitignore`,
   deployment manifests, or Git boundary documents.
