### Task 6: Final Verification

**Files:**
- No new source files unless previous tasks reveal a bug.

**Interfaces:**
- Consumes: all code and docs from Tasks 1-5.
- Produces: verification evidence for final handoff.

- [ ] **Step 1: Run focused replacement web tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run adjacent XHS note replacement tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_xhs_note_replacement.XhsNoteApiSourceTests tests.test_xhs_note_replacement.XhsNotePreviewTests -v
```

Expected: PASS. These prove the new facade did not break the existing graph for image-note replacement.

- [ ] **Step 3: Run OpenAPI contract tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_openapi_contract -v
```

Expected: PASS.

- [ ] **Step 4: Run syntax check**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m py_compile backend\api_server.py backend\replacement_web.py backend\platform_features.py tests\test_replacement_web_mvp.py
```

Expected: PASS with no output.

- [ ] **Step 5: Run diff hygiene**

Run:

```powershell
git diff --check
```

Expected: PASS or only pre-existing unrelated whitespace issues. If it fails on files touched by this plan, fix them before completion.

- [ ] **Step 6: Manual Phase 0 smoke**

Start the local execution server with the feature flag enabled:

```powershell
$env:MATRIX_REPLACEMENT_WEB_ENABLED="1"
.\.venv-win\Scripts\python.exe backend\api_server.py
```

In a separate terminal or browser:

```powershell
Invoke-WebRequest http://127.0.0.1:9080/replacement
```

Expected: HTTP 200 HTML containing `视频替换` and `图文替换`.

If terminal multipart smoke is needed, use a small local image fixture and submit both start endpoints. Do not use real provider credentials or real LK888 generation in Phase 0.

- [ ] **Step 7: Verify rollback switch**

Restart without the flag or set it to `0`:

```powershell
$env:MATRIX_REPLACEMENT_WEB_ENABLED="0"
.\.venv-win\Scripts\python.exe backend\api_server.py
```

Request:

```powershell
Invoke-WebRequest http://127.0.0.1:9080/replacement -SkipHttpErrorCheck
```

Expected: HTTP 404 JSON with `replacement_web_disabled`.

- [ ] **Step 8: Final status summary**

Record:

- changed tiers: local executor and docs/contracts;
- files changed;
- tests and smoke checks run;
- restart required: local execution server restart after changing `MATRIX_REPLACEMENT_WEB_ENABLED`;
- OpenAPI impact: new local replacement API paths;
- database/migration impact: no schema change, no-op `migration.sql`;
- rollback: set `MATRIX_REPLACEMENT_WEB_ENABLED=0`, restart local execution server, or revert touched files;
- remaining risk: Phase 0 does not prove real remote video generation or downloadable provider media.
