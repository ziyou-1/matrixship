# 2026-08-04 Video Replacement Service Task 2 Report

## Status

DONE

## Scope

Task 2 extracts source resolution and the pure analysis boundary for the local executor internal replacement-analysis layer.

This task intentionally stays inside the brief boundary:

- `backend/replacement_service.py`
- `backend/replacement_analysis.py`
- `backend/matrix_native_client.py`
- `tests/test_replacement_service.py`
- `tests/test_video_breakdown.py`

It does not modify routes, OpenAPI, billing, provider generation, remote deployment, or unrelated docs.

## Files Changed

- `backend/replacement_service.py`
- `backend/replacement_analysis.py`
- `backend/matrix_native_client.py`
- `tests/test_replacement_service.py`
- `tests/test_video_breakdown.py`

## Commit Hashes

- Baseline before Task 2: `c2f0ef7ee2895ae9e1869db41396637ac8e8966e`
- Task 2 commit: `6e7920fe2e09f6fa41cdabeb67a0869284eda00f`

## Implementation Summary

- Added `SourceResolver` in `backend/replacement_service.py` and updated `ReplacementService.prepare()` so source-resolution failures can return a structured failed job instead of incorrectly advancing to planning.
- Replaced the placeholder `backend/replacement_analysis.py` with a Qt-free pure analysis layer that provides:
  - `resolve_source(request, job_dir, progress=None)`
  - `analyze(video_path, source_url="", platform="", out_dir="", progress=None)`
- Implemented source resolution in the required order:
  1. valid handoff video + existing analysis reuse;
  2. direct `sourceUrl` download into the job directory, platform detection, validation, then analysis;
  3. `ValueError("replacement_source_required")` when no usable source exists.
- Preserved the old native helper name `_workflow_analyze_reference_video()` in `backend/matrix_native_client.py`, but converted it into a compatibility wrapper that delegates into `ReplacementAnalysis`.
- Kept `replacement_analysis.py` free of Qt imports and reused existing native helper dependencies for validation, frame extraction, OCR, transcription, vision, report generation, markdown rendering, and structured error logging.
- Added focused regression coverage for:
  - handoff source + analysis reuse without re-download;
  - direct URL download into the per-job directory with platform/host/path-hash summary;
  - invalid downloaded media returning a structured failed job without entering planned/completed flow;
  - native wrapper compatibility and the Qt-free boundary.

## Exact Commands And Results

1. Red test after adding the new tests and before implementation:

   Command:
   `.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service tests.test_video_breakdown -v`

   Result:
   `FAILED (errors=9)`

   Failure reasons:
   - `replacement_service.py` did not yet expose `SourceResolver`;
   - `_workflow_analyze_reference_video()` still executed its old inline implementation instead of delegating to the extracted analysis layer;
   - one new wrapper test initially hit a temporary Windows path permission issue until the test used a real temp directory.

2. Green focused regression suite after implementation:

   Command:
   `.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service tests.test_video_breakdown -v`

   Result:
   `Ran 53 tests in 1.775s` and `OK`

3. Compile check:

   Command:
   `.\.venv-win\Scripts\python.exe -m py_compile backend\replacement_service.py backend\replacement_analysis.py backend\matrix_native_client.py tests\test_replacement_service.py tests\test_video_breakdown.py`

   Result:
   exit code `0`

4. Diff whitespace check:

   Command:
   `git diff --check`

   Result:
   exit code `0`

   Note:
   Git emitted existing LF/CRLF warnings from the dirty worktree, including unrelated user-edited files, but no `git diff --check` errors for the Task 2 files.

5. Scoped staging:

   Command:
   `git add backend/replacement_service.py backend/replacement_analysis.py tests/test_replacement_service.py tests/test_video_breakdown.py`

   Result:
   staged the four fully owned Task 2 files.

   Command:
   `git add -p -- backend/matrix_native_client.py`

   Result:
   staged only the `_workflow_analyze_reference_video()` extraction/wrapper hunk and left unrelated user edits in `backend/matrix_native_client.py` unstaged.

6. Task 2 scoped commit:

   Command:
   `git commit -m "refactor: extract replacement video analysis service"`

   Result:
   created commit `6e7920fe2e09f6fa41cdabeb67a0869284eda00f`

## Staged Commit Contents

`git diff --cached --stat` before commit showed only the intended five files:

- `backend/matrix_native_client.py`
- `backend/replacement_analysis.py`
- `backend/replacement_service.py`
- `tests/test_replacement_service.py`
- `tests/test_video_breakdown.py`

`backend/matrix_native_client.py` was verified separately with `git diff --cached -- backend/matrix_native_client.py` to ensure only the `_workflow_analyze_reference_video()` wrapper extraction entered the commit.

## Concerns

- No blocking concerns remain for Task 2.
- The new analysis layer is still internal and fake-tested only; it does not prove real local executor downloads, real OCR/transcription/vision availability, or end-to-end replacement generation.
- `backend/matrix_native_client.py` still has unrelated user changes in the working tree outside the staged wrapper hunk; they were intentionally left untouched and uncommitted.
- This report file is intentionally left out of the Task 2 code commit, per the user instruction and consistent with Task 1 handling.

## Non-Task-2 Impact

- No OpenAPI change.
- No route change.
- No billing change.
- No database or `migration.sql` change.
- No Docker or deployment change.
- No remote AI Canvas deploy or rollback action.
- Runtime effect for the native client wrapper change still requires the user to run updated local source/build as usual; no restart was performed by this task.

## Reviewer Fix 1

### Status

DONE

### Review Findings

1. Public job responses could still expose full `sourceUrl` / nested `breakdownAnalysis` URLs including private query strings.
2. Direct-download source resolution trusted the downloader return path without checking that the file stayed inside the per-job directory.

### Files Changed

- `backend/replacement_service.py`
- `backend/replacement_analysis.py`
- `tests/test_replacement_service.py`

### Fix Commit

- Reviewer fix commit: `8d0a468a927b9597b402b66a4f86194b930a912a`

### Fix Summary

- Added a failing regression test that prepares a job with:
  - `sourceUrl=https://private.example/video/abc?sig=secret&token=secret`
  - matching private URLs nested inside handoff `breakdownAnalysis.sourceUrl`, `visual`, and `report`
- Verified that:
  - internal `job.json` still retains the original private URL for internal diagnostics;
  - public `prepare()` and `get_job()` payloads no longer expose the full URL or query credentials;
  - public output now reduces nested `http/https` URLs to the safe summary form `https://private.example/[redacted-url]`.
- Preserved the existing path redaction and credential redaction, then layered generic public URL redaction over nested scalar strings.
- Added a second failing regression test where the fake downloader returns a file path outside `job_dir`.
- Implemented an absolute containment check with `os.path.commonpath(...)` before validation or analysis accepts a direct-download source.
- Direct-download escapes now return a structured failed job with code `replacement_source_outside_job_dir` and never enter planning.
- Valid handoff reuse remains explicit and unchanged by the direct-download containment rule.

### Exact Commands And Results

1. Red regression suite before the fix:

   Command:
   `.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service tests.test_video_breakdown -v`

   Result:
   `FAILED (failures=2)`

   Failure reasons:
   - public payloads still contained `https://private.example/video/abc?sig=secret&token=[redacted]`, leaking the full path and one private query parameter;
   - a downloader path outside the job directory still advanced to `planned` instead of returning a structured rejection.

2. Green regression suite after the fix:

   Command:
   `.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service tests.test_video_breakdown -v`

   Result:
   `Ran 55 tests in 1.317s` and `OK`

3. Compile check:

   Command:
   `.\.venv-win\Scripts\python.exe -m py_compile backend\replacement_service.py backend\replacement_analysis.py backend\matrix_native_client.py tests\test_replacement_service.py tests\test_video_breakdown.py`

   Result:
   exit code `0`

4. Diff whitespace check:

   Command:
   `git diff --check`

   Result:
   exit code `0`

   Note:
   Git again emitted existing LF/CRLF warnings from unrelated dirty files in the worktree, but no `git diff --check` errors for the reviewer-fix files.

5. Scoped reviewer-fix staging:

   Command:
   `git add backend/replacement_service.py backend/replacement_analysis.py tests/test_replacement_service.py`

   Result:
   staged only the three reviewer-fix files.

6. Scoped reviewer-fix commit:

   Command:
   `git commit -m "fix: tighten replacement source redaction"`

   Result:
   created commit `8d0a468a927b9597b402b66a4f86194b930a912a`

### Concerns

- No blocking concerns remain for this reviewer-fix round.
- The URL redaction is intentionally public-response-only; internal persisted job diagnostics still keep the original URLs, consistent with the reviewer requirement.
- The new containment guard applies only to direct downloader results; valid handoff reuse still accepts an existing path outside the current job directory because that path is a previously trusted local handoff input, not a fresh downloader output.
- This report file remains intentionally uncommitted and is kept in the working tree as review input.
