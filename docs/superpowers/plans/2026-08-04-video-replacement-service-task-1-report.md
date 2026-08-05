# 2026-08-04 Video Replacement Service Task 1 Report

## Status

DONE

## Scope

Phase 0 fake end-to-end contract for the shared local video replacement service.

## Files Changed

- `backend/replacement_service.py`
- `backend/replacement_analysis.py`
- `backend/replacement_pipeline.py`
- `tests/test_replacement_service.py`

## Commit Hashes

- Baseline before Task 1: `0905b375edc4f1c2d522a266427d32d00627f351`
- Task 1 commit: `62fa0baa8e11d1cd4ed34aa2d31d211d6adb4183`

## Implementation Summary

- Added a minimal file-backed `ReplacementService` with:
  - safe `job_id` validation before path construction;
  - per-job `job.json` persistence under `data_dir/<job_id>/`;
  - atomic `job.json.tmp` writes with `os.replace`;
  - fake lifecycle support for `prepare`, `execute`, `concat`, `get_job`, and `cancel`;
  - public job serialization that strips internal local paths from returned data while keeping those paths in the persisted internal job record.
- Added minimal placeholder `ReplacementAnalysis` and `ReplacementPipeline` modules for Task 1 compile/import stability only.
- Added focused `unittest` coverage for:
  - `prepare -> planned`;
  - `execute -> awaiting_review`;
  - `concat -> completed`;
  - execute failure persistence to `failed` without a success result;
  - `cancel`;
  - missing job lookup;
  - invalid `job_id` path safety;
  - public response path redaction versus internal persisted path retention.

## Exact Commands And Results

1. Red test before implementation:

   Command:
   `.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service -v`

   Result:
   `FAILED (failures=4)`

   Failure reason:
   `replacement_service.py is missing`

2. Green test after implementation:

   Command:
   `.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service -v`

   Result:
   `Ran 4 tests in 0.031s` and `OK`

3. Compile check:

   Command:
   `.\.venv-win\Scripts\python.exe -m py_compile backend\replacement_service.py backend\replacement_analysis.py backend\replacement_pipeline.py tests\test_replacement_service.py`

   Result:
   exit code `0`

4. Diff whitespace check:

   Command:
   `git diff --check`

   Result:
   exit code `0`

   Note:
   Git emitted existing CRLF conversion warnings for unrelated user changes already present in the worktree, but no diff-check errors for Task 1 files.

5. Task 1 scoped commit:

   Command:
   `git add tests/test_replacement_service.py backend/replacement_service.py backend/replacement_analysis.py backend/replacement_pipeline.py`

   Result:
   staged only the four Task 1 code files

   Command:
   `git commit -m "test: add video replacement service contract"`

   Result:
   created commit `62fa0baa8e11d1cd4ed34aa2d31d211d6adb4183`

## Concerns

- No blocking concerns for Task 1.
- `backend/replacement_analysis.py` and `backend/replacement_pipeline.py` are intentionally minimal placeholders in this phase; they do not perform real provider work by design.
- This report file is intentionally left out of the Task 1 code commit because the brief limited the commit scope to the four Task 1 code/test files.

## Non-Task-1 Impact

- No OpenAPI changes.
- No `/replacement` route changes.
- No Qt, billing, provider, network, or production generation calls.
- No database or migration impact.
- No deployment or rollback procedure changes required for this fake contract task.

## Reviewer Fix 1

### Status

DONE

### Review Finding

- `backend/replacement_service.py` stored raw exception text in `job["error"]`, and the public serializer only dropped path-bearing keys. If an exception string embedded `outDir` or `sourceVideoPath`, `get_job()` could leak that local path text.

### Files Changed

- `backend/replacement_service.py`
- `tests/test_replacement_service.py`

### Fix Commit

- Reviewer fix commit: `c2f0ef7ee2895ae9e1869db41396637ac8e8966e`

### Fix Summary

- Added a failing regression test that raises a fake provider exception embedding:
  - the internal `outDir`;
  - the internal `sourceVideoPath`;
  - a `token=secret-token` fragment.
- Verified that the internal `job.json` still retains the raw diagnostic string, while the public `get_job()` response no longer exposes:
  - the temporary data root;
  - the absolute internal job directory;
  - the absolute internal source path;
  - the embedded token value.
- Tightened public serialization only:
  - collect internal path values from the job plus the service data root;
  - redact those path substrings from public scalar strings;
  - redact obvious credential-like fragments (`authorization`, `bearer`, `token`, `cookie`, `password`) from public scalar strings.
- Internal persistence behavior, status flow, and the fake pipeline contract remain unchanged.

### Exact Commands And Results

1. Red regression test before the fix:

   Command:
   `.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service -v`

   Result:
   `FAILED (failures=1)`

   Failure reason:
   `public_job["error"]` still contained the temporary absolute path root from the raised exception text.

2. Green regression suite after the fix:

   Command:
   `.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service -v`

   Result:
   `Ran 5 tests in 0.038s` and `OK`

3. Compile check:

   Command:
   `.\.venv-win\Scripts\python.exe -m py_compile backend\replacement_service.py backend\replacement_analysis.py backend\replacement_pipeline.py tests\test_replacement_service.py`

   Result:
   exit code `0`

4. Diff whitespace check:

   Command:
   `git diff --check`

   Result:
   exit code `0`

   Note:
   Git again emitted existing unrelated CRLF conversion warnings already present in the dirty worktree, but no diff-check errors for the Task 1 fix files.

5. Reviewer fix commit:

   Command:
   `git add backend/replacement_service.py tests/test_replacement_service.py`

   Result:
   staged only the two Task 1 fix files

   Command:
   `git commit -m "test: redact replacement service public errors"`

   Result:
   created commit `c2f0ef7ee2895ae9e1869db41396637ac8e8966e`

### Concerns

- Public redaction is intentionally narrow and string-based for Task 1: it targets embedded internal path substrings and obvious credential fragments in public scalar values without changing internal persisted diagnostics.
- This follow-up did not modify routes, OpenAPI, Qt, provider code, or unrelated dirty files.
