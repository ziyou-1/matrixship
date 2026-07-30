# Git Boundary

This file defines which project surfaces are source artifacts, which are local
runtime artifacts, and which temporary surfaces must stay visible until they are
renamed or migrated.

## Tracked source surfaces

These paths are production source, test, contract, deployment, or operator
documentation. They should be visible in `git status` and should be staged when
they are part of a release:

- Root project controls: `.gitignore`, `docker-compose.prod.yml`,
  `migration.sql`, `CHANGELOG.md`, `MIGRATION.md`, `LOCAL_TEST.md`,
  `start-local-test.ps1`, and `start-visible-client.bat`.
- Runtime source: `backend/`, including Python modules, PySide native client,
  local executor, central server, migrations, legal text, installer scripts,
  static signing files, locked requirements, and package lockfiles.
- Tests: `tests/`.
- Operator scripts: `scripts/`.
- Operational tools: `tools/`, except generated binaries or downloaded
  third-party executables that should be kept outside the repository.
- Documentation and contracts: `docs/`, including `docs/openapi.yaml`,
  `docs/ARCHITECTURE.md`, `docs/API_REFERENCE.md`,
  `docs/DEPLOYMENT.md`, `docs/IMPLEMENTATION.md`, and
  `docs/TROUBLESHOOTING.md`.
- Shell helpers: `bin/`.

## Ignored local surfaces

These paths are local runtime, validation, dependency, cache, or scratch
artifacts. They should stay out of Git:

- Python environments: `.venv/`, `.venv-win/`, and `venv/`.
- Node dependencies: `node_modules/` and `backend/node_modules/`.
- Validation output: `.tmp-validation/`.
- Runtime state: `data/`, `logs/`, `backend/central_data/`,
  `backend/datas/`, and `backend/uploads/`.
- Local rollback archives: `backups/`.
- Caches and build output: `__pycache__/`, `**/__pycache__/`, `*.pyc`,
  `dist/`, `build/`, and `*.tgz`.
- Local UI/browser helpers: `.playwright-cli/` and `.workbuddy/`.
- Downloaded local tool binaries: `tools/cloudflared` and
  `tools/cloudflared.tgz`.
- Scratch logs and temporary evidence: `*.log`, `screenlog.*`,
  `.tmp-*.log`, `.tmp-*.txt`, `.tmp-*.json`, `.tmp-*.cmd`,
  `.tmp-*.ps1`, `tmp_*.log`, `tmp_*.mp4`, and `tmp_*/`.
- Known one-off scratch scripts: `.tmp-aicanvas-ai-api-service.py`,
  `.tmp-aicanvas-test-*.py`, `.tmp-platform-*.py`,
  `.tmp-platform-test-*.py`, `.tmp-real-comic-e2e*.py`,
  `.tmp-run-prepared-comic-e2e*.py`, `.tmp-resume-real-comic-e2e.py`,
  `.tmp-recover-comic-task.py`, and `.tmp-remote-aicanvas-ops.py`.
- Local OS/editor files: `.DS_Store` and `Thumbs.db`.

## Visible transitional surfaces

These files are not normal product source, but they must remain visible until
the remote AI Canvas workflow is formalized:

- `.tmp-aicanvas-server-current.py`
- `.tmp-aicanvas-server.py`

Do not ignore `.tmp-*.py`. A broad rule would hide the two remote service
mirrors above and make remote AI Canvas changes hard to review, test, deploy,
or roll back.

Future cleanup should move these mirrors to a stable path such as
`tools/aicanvas_remote/`, then update tests and documentation references before
adding any new ignore rule.

## Operating rules

1. Treat a long `git status` as a boundary problem before starting feature work.
2. Ignore only generated, local, credential, cache, or one-off scratch artifacts.
3. Keep source, tests, contracts, deployment manifests, and operator docs
   visible.
4. Do not hide uncertain files with broad globs. Classify them first.
5. Before a release, review untracked visible files and decide whether they are
   source artifacts or transitional surfaces.
