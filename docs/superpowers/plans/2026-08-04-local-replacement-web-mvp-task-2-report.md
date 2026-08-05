# Task 2 Report: Replacement Web Support Module

## Status

DONE

## Scope Completed

- Added `backend/replacement_web.py` with the requested Phase 0 replacement web support interfaces.
- Added the replacement page HTML with video and note tabs and the two later-task API paths.
- Added HTTP(S) source URL validation, image extension/size validation, and required character-image validation.
- Added local JSON job persistence and strict task-specific job ID loading.
- Added Phase 0 video job creation without connecting LK888 or remote AI Canvas.
- Added Phase 0 note preview generation through the existing side-effect-free XHS smoke helper.
- Redacted query strings from persisted source URLs by storing only scheme, host, and a path hash.
- Persisted no upload bytes, signed URLs, authorization values, or data URLs. Uploaded filenames used by note previews are reduced to safe basenames.
- Did not modify `backend/api_server.py`, OpenAPI/API reference files, deployment docs, changelog, migration files, or unrelated worktree changes.

## TDD Evidence

RED command:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp.ReplacementWebModuleTests -v
```

Result: failed as expected with `ModuleNotFoundError: No module named 'replacement_web'` for all five new module tests.

GREEN command:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp.ReplacementWebModuleTests -v
```

Result: `Ran 5 tests ... OK`.

Regression command:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp -v
```

Result: `Ran 6 tests ... OK`, including the Task 1 feature-gate test.

Additional verification:

```powershell
.\.venv-win\Scripts\python.exe -m py_compile backend/replacement_web.py tests/test_replacement_web_mvp.py
```

Result: passed.

A direct fake-link/fake-byte persistence probe also passed. The persisted note job contained no local privacy path fragment, `token=secret`, or `data:image`.

## Commits

NONE. No staging or commit commands were run.

## Concerns

None for Task 2. Route wiring, API contract documentation, deployment documentation, migration release notes, and `docs/IMPLEMENTATION.md` line-reference updates remain intentionally deferred to later tasks as required by the brief.

## Task 2 Fix: Sensitive Note Input Redaction

### Scope

- Updated only `backend/replacement_web.py` and `tests/test_replacement_web_mvp.py` for the code fix.
- Added this fix section to the required Task 2 report only; no routes, OpenAPI, or unrelated files were changed.
- No staging or commit was performed.

### TDD Evidence

RED command:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp.ReplacementWebModuleTests.test_note_job_redacts_sensitive_business_fields_and_filenames -v
```

Result: failed as expected because `Cookie=...`, `Token=...`, `Authorization: Bearer ...`, `data:image`, and a long base64 fragment reached the persisted note job.

GREEN and required verification commands:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp.ReplacementWebModuleTests -v
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp -v
.\.venv-win\Scripts\python.exe -m py_compile backend/replacement_web.py tests/test_replacement_web_mvp.py
```

Results: module tests `Ran 6 tests ... OK`; complete MVP tests `Ran 7 tests ... OK`; compilation passed.

### Fix Summary

- Added note-input sanitization for credential words/values, `data:image` payload-shaped values, and long base64 fragments.
- Sanitized business fields and filenames before invoking the XHS smoke helper.
- Sanitized helper output before writing `job.json` and sanitized note fields again in `job_response()`.
- Normal Chinese business text remains present in the persisted job.

### Concerns

None within the requested fix scope.

## Controller Fix Addendum

After re-review found URL userinfo leakage, controller added regression coverage for source URLs with userinfo credentials and changed `_safe_url_parts()` to reject URLs with parsed username/password and persist only hostname plus port. Verification passed: module tests 7/7, full replacement web tests 8/8, and `py_compile` for `backend/replacement_web.py` plus `tests/test_replacement_web_mvp.py`.





