# 2026-08-04 Task 3 Review - hybrid_v2 pipeline extraction

## Verdicts

- Spec compliance: **Not approved**
- Task quality: **Not approved**

## Findings

### Critical

1. **Public replacement events still leak absolute local segment paths.**  
   In [backend/replacement_pipeline.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/backend/replacement_pipeline.py:16), the new scrubber only removes keys listed in `_PRIVATE_KEYS`, but `sourceSegmentPath` is not in that set and is therefore preserved by `public_job()` / `public_segments()` ([backend/replacement_pipeline.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/backend/replacement_pipeline.py:239), [backend/replacement_pipeline.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/backend/replacement_pipeline.py:342)). Non-talking hybrid generation writes an absolute `sourceSegmentPath` into each segment ([backend/matrix_native_client.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/backend/matrix_native_client.py:24455)), and those scrubbed segments are then emitted in public progress / done payloads ([backend/matrix_native_client.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/backend/matrix_native_client.py:15470), [backend/matrix_native_client.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/backend/matrix_native_client.py:15990)). This violates the task constraint that public responses/events must never expose absolute local paths.

### Important

1. **User cancellation now bubbles out as a generic failure after the cancel path has already run.**  
   `HybridReplacementPipeline._run_segment()` re-raises cancellation after marking the segment/job canceled ([backend/replacement_pipeline.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/backend/replacement_pipeline.py:262)), and `execute()` does not intercept that path before unwinding ([backend/replacement_pipeline.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/backend/replacement_pipeline.py:137)). The caller in `start_generation()` catches the propagated exception as a generic failure and emits a second `"替换生成失败"` terminal event ([backend/matrix_native_client.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/backend/matrix_native_client.py:15553)). Before this extraction, `_run_job_segments()` handled cancel locally and returned without converting it into a failure. The new behavior can overwrite a clean cancel with a failed state and produces conflicting terminal events for the same job.

## Notes

- I did not rerun the full focused suite from the implementer report.
- I inspected the brief, implementer report, review package diff, and surrounding runtime logic needed to verify the binding constraints.

## Re-review (9f27ce3)

### Prior findings status

1. **Resolved: `public_job()` / `public_segments()` now scrub the internal segment paths called out in the original review.**  
   `sourceSegmentPath` and `sourceSegmentUploadPath` were added to `_PRIVATE_KEYS` in [backend/replacement_pipeline.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/backend/replacement_pipeline.py:16), and the new regression `test_hybrid_pipeline_public_payloads_hide_internal_segment_paths` covers that exact payload shape in [tests/test_video_replacement_v2.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/tests/test_video_replacement_v2.py:1280).

2. **Resolved: execute-time cancellation no longer bubbles into the caller's generic failure handler.**  
   `HybridReplacementPipeline.execute()` now catches the known cancel path and returns the canceled job instead of re-raising it to `start_generation()` ([backend/replacement_pipeline.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/backend/replacement_pipeline.py:159)). The new regression `test_hybrid_pipeline_execute_returns_canceled_job_after_segment_cancellation` verifies the returned status is `canceled` instead of a spurious failure ([tests/test_video_replacement_v2.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/tests/test_video_replacement_v2.py:1401)).

### New findings

#### Important

1. **Hybrid cancel completion still emits an unsanitized public job payload.**  
   The new cancel handling in `HybridReplacementPipeline.execute()` returns cleanly, but the underlying cancel helper still emits `video_replace_done` with the raw `job` object from `_mark_replacement_job_canceled()` instead of a scrubbed public view ([backend/matrix_native_client.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/backend/matrix_native_client.py:11692)). The hybrid pipeline still routes cancellation through that helper from `_run_segment()` ([backend/replacement_pipeline.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/backend/replacement_pipeline.py:269)). That raw terminal event can still expose fields such as `outDir`, `sourceVideoPath`, `videoPath`, and, after source-segment extraction has started, `sourceSegmentPath`, so the package still does not fully satisfy the binding rule that public responses/events must never expose absolute local paths. The new regression only asserts the returned job object, not the emitted public payload.

### Re-review verdicts

- Spec compliance: **Not approved**
- Task quality: **Not approved**

### Re-review notes

- Based on the provided report, the two focused regression tests passed.
- I did not treat the initial 387-test failure as a Task 3 defect because the user identified it as coming from unrelated dirty working-tree configuration outside commits `0d854de` and `9f27ce3`; the same suite passed with `MATRIX_CENTRAL=http://127.0.0.1:9080`.

## Final Re-review (8fd30f4)

### Prior findings status

1. **Resolved: public segment path leakage is closed.**  
   The earlier path leak via `public_job()` / `public_segments()` remains fixed by the `_PRIVATE_KEYS` additions in [backend/replacement_pipeline.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/backend/replacement_pipeline.py:16), and the regression coverage for scrubbed segment payloads is still present in [tests/test_video_replacement_v2.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/tests/test_video_replacement_v2.py:1280).

2. **Resolved: execute-time cancellation no longer degrades into a generic failure.**  
   `HybridReplacementPipeline.execute()` still intercepts the known cancel path and returns the canceled job cleanly in [backend/replacement_pipeline.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/backend/replacement_pipeline.py:159), with focused regression coverage in [tests/test_video_replacement_v2.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/tests/test_video_replacement_v2.py:1401).

3. **Resolved: canceled terminal events now emit a scrubbed public job.**  
   `_mark_replacement_job_canceled()` now emits `_replacement_public_job(job)` instead of the raw internal job in [backend/matrix_native_client.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/backend/matrix_native_client.py:11692). The new regression `test_cancel_completion_event_uses_public_job_without_internal_paths` verifies both sides of the contract: persisted state retains internal paths, while the emitted `video_replace_done` payload contains neither internal path keys nor their values ([tests/test_video_replacement_v2.py](E:/Desktop/矩阵星舰_应用前后端与中心服源码_clean_20260710_150252/tests/test_video_replacement_v2.py:1445)).

### New findings

- None.

### Final verdicts

- Spec compliance: **Approved**
- Task quality: **Approved**

### Final notes

- Based on the provided report, the three focused cancellation/redaction regressions passed.
- I did not treat the `MATRIX_CENTRAL` override as a Task 3 issue because the user scoped it to unrelated dirty working-tree configuration outside commits `0d854de`, `9f27ce3`, and `8fd30f4`; under `MATRIX_CENTRAL=http://127.0.0.1:9080`, the full 388-test Task 3 suite passed.
