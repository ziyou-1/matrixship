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

## Fix Follow-up

### Review findings addressed
- Added `sourceSegmentPath` and `sourceSegmentUploadPath` to the hybrid pipeline private scrub list so public job/progress payloads do not expose absolute local segment paths.
- Updated `HybridReplacementPipeline.execute()` to return the canceled job when segment execution raises the known cancel signal, instead of bubbling that path into the caller's generic failure handler.
- Added focused regressions for public payload scrubbing and execute-time cancellation.

### Focused regression output
```text
.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_hybrid_pipeline_public_payloads_hide_internal_segment_paths tests.test_video_replacement_v2.VideoReplacementV2Test.test_hybrid_pipeline_execute_returns_canceled_job_after_segment_cancellation -v
test_hybrid_pipeline_public_payloads_hide_internal_segment_paths (tests.test_video_replacement_v2.VideoReplacementV2Test.test_hybrid_pipeline_public_payloads_hide_internal_segment_paths) ... ok
test_hybrid_pipeline_execute_returns_canceled_job_after_segment_cancellation (tests.test_video_replacement_v2.VideoReplacementV2Test.test_hybrid_pipeline_execute_returns_canceled_job_after_segment_cancellation) ... ok

----------------------------------------------------------------------
Ran 2 tests in 0.229s

OK
```

### Required verification output
```text
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service tests.test_video_replacement tests.test_video_replacement_v2 -q
======================================================================
FAIL: test_keyframe_references_migrate_existing_central_library_urls_in_memory (tests.test_video_replacement_v2.VideoReplacementV2Test.test_keyframe_references_migrate_existing_central_library_urls_in_memory)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "E:\Desktop\�����ǽ�_Ӧ��ǰ��������ķ�Դ��_clean_20260710_150252\tests\test_video_replacement_v2.py", line 1620, in test_keyframe_references_migrate_existing_central_library_urls_in_memory
    self.assertEqual(len(refs), 3)
AssertionError: 0 != 3

----------------------------------------------------------------------
Ran 387 tests in 10.081s

FAILED (failures=1)
```

```text
.\.venv-win\Scripts\python.exe -m py_compile backend\replacement_pipeline.py backend\matrix_native_client.py tests\test_replacement_service.py
```

```text
git diff --check
warning: in the working copy of 'CHANGELOG.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'backend/.env.example', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'backend/api_server.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'backend/build_matrix_agent.ps1', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'backend/installer/MatrixShipAgent.iss', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'backend/matrix_native_client.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'backend/platform_features.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'backend/replacement_pipeline.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'docs/API_REFERENCE.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'docs/ARCHITECTURE.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'docs/DEPLOYMENT.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'docs/IMPLEMENTATION.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'docs/TROUBLESHOOTING.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'docs/openapi.yaml', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'docs/superpowers/plans/2026-08-04-video-replacement-service-task-3-report.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'migration.sql', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'tests/test_login_centered_layout.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'tests/test_minimax_aicanvas_remote.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'tests/test_native_enterprise_invite.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'tests/test_video_breakdown.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'tests/test_video_replacement_v2.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'tests/test_web_surface_removed.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'tools/aicanvas_remote/server_current.py', LF will be replaced by CRLF the next time Git touches it
```

## Cancellation Event Follow-up

- Changed the cancellation terminal event to emit `_replacement_public_job(job)` while keeping the persisted internal job unchanged.
- Added `test_cancel_completion_event_uses_public_job_without_internal_paths` to verify that local paths remain available internally but are absent from `video_replace_done`.

```text
.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement_v2.VideoReplacementV2Test.test_cancel_completion_event_uses_public_job_without_internal_paths tests.test_video_replacement_v2.VideoReplacementV2Test.test_hybrid_pipeline_public_payloads_hide_internal_segment_paths tests.test_video_replacement_v2.VideoReplacementV2Test.test_hybrid_pipeline_execute_returns_canceled_job_after_segment_cancellation -v

----------------------------------------------------------------------
Ran 3 tests in 0.430s

OK
```

```text
$env:MATRIX_CENTRAL='http://127.0.0.1:9080'; .\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service tests.test_video_replacement tests.test_video_replacement_v2 -q

----------------------------------------------------------------------
Ran 388 tests in 11.665s

OK
```

The explicit `MATRIX_CENTRAL` value isolates Task 3 from an unrelated dirty working-tree change that points the client default at the remote central service; the legacy migration test uses `127.0.0.1:9080` as its fixture origin.
