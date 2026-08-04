# 2026-08-04 Task 3 Report - hybrid_v2 pipeline extraction

## Scope
- Task base: `8d0a468`
- Tier: native client / local replacement pipeline
- Goal: finish Task 3 from the existing working tree, keep prior Task 3 extraction work, and fix the focused `tests.test_video_replacement_v2` loader failure without touching unrelated dirty changes.

## Root cause
- `backend/matrix_native_client.py` created `HybridReplacementPipeline` with `helpers=sys.modules[__name__]`.
- `tests.test_video_replacement_v2` loads `matrix_native_client.py` through `importlib.util.module_from_spec(...)` under the temporary name `matrix_native_client_for_replacement_v2` without inserting that name into `sys.modules`.
- `_replacement_hybrid_pipeline()` and `_replacement_public_job()` therefore raised `KeyError` during `_build_job()` and preflight-failure cleanup.

## Fix
- Kept the existing Task 3 extraction intact.
- Replaced the direct `sys.modules[__name__]` lookup with a live `_ReplacementHelperProxy(globals())` adapter so helper resolution still tracks the active module namespace, including test-time monkeypatches, without requiring the temporary loader name to exist in `sys.modules`.
- Checked the surrounding Task 3 helper path and found no second `sys.modules[__name__]` usage in the hybrid pipeline bridge.

## Changed files
- `backend/replacement_pipeline.py`
- `backend/matrix_native_client.py`
- `tests/test_replacement_service.py`
- `tests/test_video_replacement.py`
- `tests/test_video_replacement_v2.py`
- `docs/superpowers/plans/2026-08-04-video-replacement-service-task-3-report.md`

## Verification

### Focused repro before fix
```text
.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2 -q

FAILED (errors=2)
- KeyError: 'matrix_native_client_for_replacement_v2'
- failing sites: _replacement_hybrid_pipeline(), _replacement_public_job()
```

### Focused suite after fix
```text
.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2 -q

----------------------------------------------------------------------
Ran 269 tests in 13.279s

OK
```

### Required verification commands
```text
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service tests.test_video_replacement tests.test_video_replacement_v2 -q

----------------------------------------------------------------------
Ran 385 tests in 11.623s

OK
```

```text
.\.venv-win\Scripts\python.exe -m py_compile backend\replacement_pipeline.py backend\matrix_native_client.py tests\test_replacement_service.py

[exit 0]
```

```text
git diff --check

[exit 0]
note: only LF->CRLF working-tree warnings were emitted for unrelated existing dirty files; no diff-check errors were reported.
```

## Operational impact
- Restart/deploy required: none performed in this task.
- OpenAPI / database / Docker / migration impact: none.
- Rollback path: revert the Task 3 commit `refactor: extract hybrid replacement pipeline`.

## Remaining risk
- Verification is source-level only; no native client restart or real LK888 / remote AI Canvas smoke was performed in this task.
