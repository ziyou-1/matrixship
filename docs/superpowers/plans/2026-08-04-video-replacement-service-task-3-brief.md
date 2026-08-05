## Task 3: hybrid_v2 Pipeline

**Files:**
- Modify: backend/replacement_pipeline.py
- Modify: backend/matrix_native_client.py lines 15242-15557, 24870-24943 and 25410-25479
- Modify: tests/test_replacement_service.py, tests/test_video_replacement.py and tests/test_video_replacement_v2.py

**Interfaces:**
- HybridReplacementPipeline.build_plan(job) -> dict
- HybridReplacementPipeline.execute(job, selected_segments, progress=None) -> dict
- HybridReplacementPipeline.retry(job, segment_indices, progress=None) -> dict
- HybridReplacementPipeline.concat(job) -> dict

- [ ] Step 1: Add failing tests for plan, segment generation, QC, partial failure and targeted retry.

Assert source entities and scripts are preserved, a successful fake segment has status done and qcStatus passed, one failed segment makes the job partial, retry only changes the requested failed segment, provider exceptions never create a success result, and invalid media never reaches awaiting_review.

- [ ] Step 2: Run focused tests to establish the red state.

~~~powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service tests.test_video_replacement tests.test_video_replacement_v2 -v
~~~

- [ ] Step 3: Move page-independent hybrid orchestration into HybridReplacementPipeline.

Extract the logic from VideoReplacementPage._build_job, the non-comic branch of _run_job_segments, _run_hybrid_replacement_segment, _run_replacement_segment and concat preparation. Pass model, audio, references, analysis and preflight through the job. Progress callbacks receive jobId, stage, message, segmentIndex and a sanitized segments list. Persist after each segment and each provider state transition.

- [ ] Step 4: Run hybrid tests, compile and diff check.

~~~powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service tests.test_video_replacement tests.test_video_replacement_v2 -v
.\.venv-win\Scripts\python.exe -m py_compile backend\replacement_pipeline.py backend\matrix_native_client.py tests\test_replacement_service.py
git diff --check
~~~

- [ ] Step 5: Commit the hybrid extraction.

~~~powershell
git add backend/replacement_pipeline.py backend/matrix_native_client.py tests/test_replacement_service.py tests/test_video_replacement.py tests/test_video_replacement_v2.py
git commit -m "refactor: extract hybrid replacement pipeline"
~~~

