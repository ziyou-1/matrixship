## Task 1: Phase 0 Fake Contract

**Files:**
- Create: backend/replacement_service.py
- Create: backend/replacement_analysis.py
- Create: backend/replacement_pipeline.py
- Create: tests/test_replacement_service.py

**Interfaces:**
- ReplacementService(data_dir, source_resolver, pipeline, runtime=None)
- prepare(job_id, request, files, progress=None) -> dict
- execute(job_id, overrides=None, progress=None) -> dict
- concat(job_id, progress=None) -> dict
- get_job(job_id) -> dict | None
- cancel(job_id) -> dict

- [ ] Step 1: Write failing fake lifecycle tests.

Use temporary data and these injectable fakes:

~~~python
class FakeSourceResolver:
    def prepare(self, job, request, progress=None):
        job["sourceVideoPath"] = os.path.join(job["outDir"], "source.mp4")
        Path(job["sourceVideoPath"]).write_bytes(b"fake-video")
        job["breakdownAnalysis"] = {"meta": {"duration": 8.0}}
        return job

class FakePipeline:
    def build_plan(self, job):
        job["segments"] = [{"index": 1, "start": 0.0, "end": 8.0, "status": "planned"}]
        return job

    def execute(self, job, selected_segments=None, progress=None):
        segment = job["segments"][0]
        output = os.path.join(job["outDir"], "segment-01.mp4")
        Path(output).write_bytes(b"fake-output")
        segment.update({"status": "done", "videoPath": output, "qcStatus": "passed"})
        job["status"] = "awaiting_review"
        return job

    def concat(self, job):
        output = os.path.join(job["outDir"], "final.mp4")
        Path(output).write_bytes(b"fake-final")
        job.update({"status": "completed", "outputPath": output})
        return job
~~~

Assert prepare creates a job and plan, execute reaches awaiting_review, concat reaches completed, and a fake provider exception reaches failed without a success result.

- [ ] Step 2: Run the focused test and verify the contract fails.

~~~powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service -v
~~~

Expected: FAIL because ReplacementService and the lifecycle methods are absent.

- [ ] Step 3: Implement the minimal file-backed service.

Use atomic job.json.tmp plus os.replace, validate job IDs before path construction, and keep internal paths only in the job file. The public response serializer must never expose those paths.

~~~python
class ReplacementService:
    def __init__(self, data_dir, source_resolver, pipeline, runtime=None):
        self.data_dir = os.path.abspath(data_dir)
        self.source_resolver = source_resolver
        self.pipeline = pipeline
        self.runtime = runtime

    def prepare(self, job_id, request, files, progress=None):
        job = self._create_job(job_id, request, files)
        self._write_job(job)
        job = self.source_resolver.prepare(job, request, progress=progress)
        job = self.pipeline.build_plan(job)
        job["status"] = "planned"
        self._write_job(job)
        return job

    def execute(self, job_id, overrides=None, progress=None):
        job = self._load_job(job_id)
        if not job or job.get("status") != "planned":
            raise ValueError("replacement_job_not_planned")
        self._apply_overrides(job, overrides or {})
        job["status"] = "running"
        self._write_job(job)
        job = self.pipeline.execute(
            job, selected_segments=job.get("segments") or [], progress=progress
        )
        self._write_job(job)
        return job

    def concat(self, job_id, progress=None):
        job = self._load_job(job_id)
        if not job or job.get("status") != "awaiting_review":
            raise ValueError("replacement_job_not_ready_for_concat")
        job = self.pipeline.concat(job)
        self._write_job(job)
        return job
~~~

- [ ] Step 4: Run tests, compile and diff check.

~~~powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service -v
.\.venv-win\Scripts\python.exe -m py_compile backend\replacement_service.py backend\replacement_analysis.py backend\replacement_pipeline.py tests\test_replacement_service.py
git diff --check
~~~

Expected: fake lifecycle tests pass and all new modules compile.

- [ ] Step 5: Commit only the Task 1 files.

~~~powershell
git add tests/test_replacement_service.py backend/replacement_service.py backend/replacement_analysis.py backend/replacement_pipeline.py
git commit -m "test: add video replacement service contract"
~~~

