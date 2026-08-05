## Task 2: Source Resolution and Analysis Boundary

**Files:**
- Modify: backend/replacement_service.py
- Modify: backend/replacement_analysis.py
- Modify: backend/matrix_native_client.py lines 8048-8246 and 17950-18115
- Modify: tests/test_replacement_service.py and tests/test_video_breakdown.py

**Interfaces:**
- SourceResolver.prepare(job, request, progress=None) -> dict
- ReplacementAnalysis.resolve_source(request, job_dir, progress=None) -> dict
- ReplacementAnalysis.analyze(video_path, source_url="", platform="", out_dir="", progress=None) -> dict

- [ ] Step 1: Add failing tests for handoff reuse, direct URL download and invalid media.

Use fake download, validation, OCR, transcription and vision adapters. Assert handoff reuses its source and analysis, direct URL resolves platform and writes within the job directory, and invalid media returns structured failure without completed status.

- [ ] Step 2: Run the source tests before implementation.

~~~powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service tests.test_video_breakdown -v
~~~

Expected: new resolver tests fail while existing video breakdown tests remain the compatibility baseline.

- [ ] Step 3: Extract the pure workflow represented by _workflow_analyze_reference_video into replacement_analysis.py.

Keep a compatibility wrapper with the old native function name. Preserve validation, meta, ocr, transcript, visual, report, sourceUrl, videoPath and error ID fields. Resolve sources in this order:

~~~python
if valid_handoff_video(handoff):
    use_handoff_video_and_analysis()
elif source_url:
    platform = platform_from_url(source_url)
    video_path = platform_downloader.download(source_url, job_dir)
    validate_video_file(video_path)
    analyze(video_path, source_url=source_url, platform=platform)
else:
    raise ValueError("replacement_source_required")
~~~

Persist absolute paths internally only; public responses contain platform, host, duration, availability and a path hash.

- [ ] Step 4: Run analysis regression tests and compile.

~~~powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service tests.test_video_breakdown -v
.\.venv-win\Scripts\python.exe -m py_compile backend\replacement_analysis.py backend\matrix_native_client.py tests\test_replacement_service.py tests\test_video_breakdown.py
git diff --check
~~~

- [ ] Step 5: Commit the source boundary.

~~~powershell
git add backend/replacement_service.py backend/replacement_analysis.py backend/matrix_native_client.py tests/test_replacement_service.py tests/test_video_breakdown.py
git commit -m "refactor: extract replacement video analysis service"
~~~

