## Task 4: comic_project Recovery, Fallback and Billing

**Files:**
- Modify: backend/replacement_pipeline.py
- Modify: backend/matrix_native_client.py lines 928-1072, 15640-15975 and 16278-16840
- Modify: tests/test_replacement_service.py, tests/test_video_replacement.py and tests/test_video_replacement_v2.py

**Interfaces:**
- ComicProjectReplacementPipeline.build_plan(job) -> dict
- ComicProjectReplacementPipeline.execute(job, selected_segments, progress=None) -> dict
- ComicProjectReplacementPipeline.retry(job, segment_indices, progress=None) -> dict
- ComicProjectReplacementPipeline.regenerate_frame(job, segment_index, frame_kind, progress=None) -> dict
- settle_actual_cost(job, segment, payload, media_kind, task_id, frame_index=None) -> dict

- [ ] Step 1: Add failing fake adapter tests.

Cover existing remote video recovery without submit, submit timeout recovery before fallback, start/end frame recovery, model fallback reason persistence, missing cost returning awaiting_actual_cost, and keyframe/video billing refs being distinct. Assert the same provider task is not submitted twice.

~~~python
def test_actual_billing_is_idempotent_and_ignores_submit_estimate(self):
    payload = {"task_id": "provider-1", "cost": 0.42, "estimated_cost": 9.99}
    first = settle_actual_cost(job, segment, payload, "video", "provider-1")
    second = settle_actual_cost(job, segment, payload, "video", "provider-1")
    self.assertEqual(first["ref"], second["ref"])
    self.assertEqual(self.charge.calls, 1)
    self.assertEqual(first["actualAmount"], 0.42)
~~~

- [ ] Step 2: Run the red tests.

~~~powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service tests.test_video_replacement tests.test_video_replacement_v2 -v
~~~

- [ ] Step 3: Extract the page-independent comic orchestration.

Preserve this order for every segment:

~~~text
load/recover storyboard
  -> update script and assets
  -> submit or recover start/end frames
  -> wait and download validated frames
  -> submit or recover video
  -> wait and download validated video
  -> settle final actual cost once
  -> persist segment
~~~

Keep existing recovery lookup and fallback predicates. Never submit fallback before checking the original task. Persist requested model, actual model, task IDs, recovery reason and billing state.

- [ ] Step 4: Run comic, billing and compile checks.

~~~powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service tests.test_video_replacement tests.test_video_replacement_v2 -v
.\.venv-win\Scripts\python.exe -m py_compile backend\replacement_pipeline.py backend\matrix_native_client.py tests\test_replacement_service.py
git diff --check
~~~

- [ ] Step 5: Commit the comic extraction.

~~~powershell
git add backend/replacement_pipeline.py backend/matrix_native_client.py tests/test_replacement_service.py tests/test_video_replacement.py tests/test_video_replacement_v2.py
git commit -m "refactor: extract comic replacement pipeline"
~~~

