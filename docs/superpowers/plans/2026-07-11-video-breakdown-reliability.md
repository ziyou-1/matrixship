# Video Breakdown Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one-click video breakdown reliably download authenticated Douyin video, reject invalid media, repair existing bad materials without changing IDs, run Tesseract OCR, and transcribe up to 10 minutes through chunked LK888 Gemini audio requests.

**Architecture:** Add shared validation and structured-log helpers under `backend/utils`, harden the existing downloader before either local or central import, and keep transcription as a testable utility called by the native client. Existing `/lk888/*` proxying and session authentication remain authoritative; no API key is added to client code.

**Tech Stack:** Python 3.12, requests, imageio-ffmpeg/ffmpeg, PySide6, Tesseract, pytesseract, Pillow, unittest, LK888 Gemini native `generateContent`.

## Global Constraints

- Use authenticated HTTP download with Douyin Cookie, existing browser User-Agent, Referer, Accept, and Range headers.
- Download to `.part`; only `os.replace()` after HTTP, content, and ffmpeg validation passes.
- Preserve local and central material IDs when repairing invalid historical files.
- Tesseract language is `chi_sim+eng`; OCR failure degrades without blocking the report.
- Audio is mono 16 kHz 64 kbps MP3, split into 60-second chunks, processed sequentially for at most 600 seconds.
- Gemini model defaults to `gemini-3.1-pro-preview`, timeout is 180 seconds, retries are 2, and client concurrency is 1.
- Do not hardcode API keys, cookies, signed URLs, or Authorization headers in code, tests, docs, or logs.
- New error logs are one-line JSON with stack, redacted context, and stable `errorId`.
- No database schema change, migration SQL, Docker image, or new public business API is required.
- The workspace is not a Git repository. Replace commit steps with timestamped snapshot checkpoints and SHA256 manifests.

---

### Task 1: Backup Snapshot and Phase 0 Feasibility Smoke

**Files:**
- Snapshot: `backups/video-breakdown-reliability-<timestamp>/`
- Create during smoke: `/tmp/matrixship-transcription-smoke/`
- Modify after smoke: `docs/TROUBLESHOOTING.md`

**Interfaces:**
- Consumes: current source tree, active local center session, bundled ffmpeg, existing Douyin login state.
- Produces: restorable source snapshot, SHA256 manifest, recorded smoke evidence for download, OCR, and Gemini audio.

- [ ] **Step 1: Create a timestamped source snapshot**

Back up these files before production edits:

```text
backend/utils/data_util.py
backend/api_server.py
backend/central_server.py
backend/matrix_native_client.py
backend/requirements.txt
backend/requirements.deploy.txt
docs/TROUBLESHOOTING.md
```

Use `shasum -a 256` to create `SHA256SUMS.txt` inside the snapshot directory. Copying is allowed for backup creation; production code edits still use `apply_patch`.

- [ ] **Step 2: Verify authenticated Douyin CDN feasibility**

Read `video_addr` from the existing failed material metadata without printing Cookie values. Request only a small range using the account's current Cookie plus:

```text
User-Agent: HeaderBuilder.ua
Referer: https://www.douyin.com/
Accept: video/*,*/*;q=0.8
Range: bytes=0-1023
```

Expected: HTTP 200 or 206 and `Content-Type: video/mp4`, not HTML.

- [ ] **Step 3: Install and smoke-test OCR dependencies**

Run:

```bash
brew install tesseract tesseract-lang
.venv/bin/pip install 'Pillow==11.3.0' 'pytesseract==0.3.13'
```

Generate a small image containing `注意事项 测试字幕` using Pillow and verify `pytesseract.image_to_string(..., lang='chi_sim+eng', config='--oem 3 --psm 11')` returns non-empty text containing at least one expected Chinese token.

- [ ] **Step 4: Smoke-test LK888 Gemini audio input**

Generate a one-second MP3 with ffmpeg, submit it through the authenticated local center route:

```text
POST http://127.0.0.1:9080/lk888/v1beta/models/gemini-3.1-pro-preview:generateContent
```

Use `inline_data` with `mime_type=audio/mpeg`. Expected: HTTP 200 and non-empty `candidates[0].content.parts[].text`. Do not print session tokens or Base64 audio.

- [ ] **Step 5: Record smoke outcomes**

Append the exact status, failure point, and remediation to `docs/TROUBLESHOOTING.md`. If Gemini native audio is unavailable, stop implementation of transcription and record the upstream response because the selected architecture would be invalid.

---

### Task 2: Shared Media Validation and Structured Logging

**Files:**
- Create: `backend/utils/media_validation.py`
- Create: `backend/utils/structured_log.py`
- Create: `tests/test_media_validation.py`
- Create: `tests/test_structured_log.py`

**Interfaces:**
- Produces: `probe_media(path: str, ffmpeg_exe: str | None = None) -> dict`
- Produces: `validate_video_file(path: str, content_type: str = '', ffmpeg_exe: str | None = None) -> dict`
- Produces: `looks_like_error_document(path: str) -> bool`
- Produces: `quarantine_file(path: str, quarantine_root: str, material_id: str, reason: str) -> str`
- Produces: `cleanup_quarantine(root: str, retention_days: int) -> int`
- Produces: `redact_url(url: str) -> str`
- Produces: `json_log(logger, event: str, level: str = 'error', exc: BaseException | None = None, **context) -> str`

- [ ] **Step 1: Write failing validation tests**

Create tests that assert:

```python
def test_html_named_mp4_is_rejected():
    path.write_text('<html><h1>403 Forbidden</h1></html>')
    result = validate_video_file(str(path), 'text/html')
    assert result['ok'] is False
    assert result['code'] in {'download_unexpected_content_type', 'download_html_body'}

def test_valid_generated_mp4_reports_video_metadata():
    result = validate_video_file(str(generated_mp4), 'video/mp4')
    assert result['ok'] is True
    assert result['duration'] > 0
    assert result['width'] > 0
    assert result['height'] > 0
    assert result['hasVideo'] is True
```

Add tests for missing files, audio-only files, invalid dimensions, quarantine preservation, and retention cleanup.

- [ ] **Step 2: Write failing redaction tests**

Assert that a signed URL retains only scheme, host, path, and query-key names; assert JSON logs contain `event`, `errorId`, `stack`, and context but never Cookie, Authorization, API Key, query values, or Base64.

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_media_validation tests.test_structured_log -v
```

Expected: import failures because the new utility modules do not exist.

- [ ] **Step 4: Implement minimal shared utilities**

`validate_video_file()` must:

```python
if not os.path.isfile(path):
    return {'ok': False, 'code': 'media_missing_file', ...}
if content_type.lower().split(';', 1)[0] in {'text/html', 'application/json'}:
    return {'ok': False, 'code': 'download_unexpected_content_type', ...}
if looks_like_error_document(path):
    return {'ok': False, 'code': 'download_html_body', ...}
meta = probe_media(path, ffmpeg_exe)
if not meta['hasVideo']:
    return {'ok': False, 'code': 'media_missing_video_stream', ...}
return {'ok': True, 'code': 'ok', **meta}
```

Use `imageio_ffmpeg.get_ffmpeg_exe()` when no executable is injected. Parse `Duration`, `Video:`, `Audio:`, and dimensions from ffmpeg output. Quarantine through atomic move when source and target are on the same filesystem, otherwise copy then remove.

- [ ] **Step 5: Run tests and verify GREEN**

Run the focused test command again. Expected: all validation and log tests pass.

- [ ] **Step 6: Create snapshot checkpoint**

Copy new utility modules and tests into `backups/.../checkpoint-task-2/` and append their SHA256 hashes to the manifest.

---

### Task 3: Authenticated Atomic Douyin Download

**Files:**
- Modify: `backend/utils/data_util.py`
- Modify: `backend/api_server.py`
- Create: `tests/test_authenticated_download.py`

**Interfaces:**
- Consumes: `validate_video_file()`, `json_log()`, current `DouyinAuth.cookie`, `HeaderBuilder.ua`.
- Produces: `download_media(path, name, url, media_type, auth=None, source_url='', timeout=None) -> dict`
- Produces: `download_work(work_info, path, save_choice, auth=None) -> str`
- Produces: structured `MediaDownloadError(code, context)`.

- [ ] **Step 1: Write failing downloader tests**

Using a fake streaming response, assert:

```python
result = download_media(..., auth=fake_auth)
assert request_headers['Referer'] == 'https://www.douyin.com/'
assert request_headers['Range'] == 'bytes=0-'
assert request_headers['User-Agent']
assert request_cookies == fake_auth.cookie
```

Add tests that a 403 response raises `MediaDownloadError('download_http_403')`, HTML is rejected, `.part` is deleted, and an existing valid destination is not overwritten on failure.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_authenticated_download -v
```

Expected: current downloader does not pass auth headers and incorrectly writes HTML.

- [ ] **Step 3: Implement atomic authenticated download**

Use `requests.get(..., stream=True, headers=headers, cookies=auth.cookie, timeout=(20, configured_timeout))`. Stream to `<name>.mp4.part`, call `raise_for_status()` semantics through explicit status handling, validate the completed `.part`, then `os.replace(part_path, final_path)`.

Return validation metadata without Cookie or signed URL values. Raise typed errors with structured JSON logging and full stack for unexpected exceptions.

- [ ] **Step 4: Refresh signed URL once on 403**

In `/api/douyin/download`:

```python
work = SPIDER.spider_work(auth, url)
try:
    save_path = download_work(work, BASE_PATH['media'], save_choice, auth=auth)
except MediaDownloadError as exc:
    if exc.code != 'download_http_403':
        raise
    work = SPIDER.spider_work(auth, url)
    save_path = download_work(work, BASE_PATH['media'], save_choice, auth=auth)
```

The second failure must return an explicit non-200 API response and must not call library import.

- [ ] **Step 5: Run tests and regression suite**

Run focused tests, then:

```bash
.venv/bin/python -m unittest discover tests -v
```

Expected: all tests pass.

- [ ] **Step 6: Create snapshot checkpoint**

Back up modified downloader and API server files with updated SHA256 hashes.

---

### Task 4: Invalid-Material Rejection and In-Place ID Repair

**Files:**
- Modify: `backend/api_server.py`
- Modify: `backend/central_server.py`
- Create: `tests/test_material_repair.py`

**Interfaces:**
- Consumes: `validate_video_file()`, `quarantine_file()`, `cleanup_quarantine()`.
- Produces: local and central material dictionaries with unchanged `id` and optional `repaired`, `repairedAt`, `duration`, `width`, `height` fields.

- [ ] **Step 1: Write failing local repair tests**

Build a temporary local library with one source-key match whose `video.mp4` contains HTML. Import a valid generated MP4 with the same source key and assert:

```python
assert repaired['id'] == original_id
assert repaired['repaired'] is True
assert validate_video_file(repaired_path)['ok'] is True
assert quarantine_contains_old_html(original_id)
```

Also assert a new invalid candidate creates no library record.

- [ ] **Step 2: Write failing central repair tests**

Patch central `STATE`, material root, and persistence. Mirror a valid node material over an invalid existing central item and assert the central ID, published count, and createdAt are preserved while the file becomes valid.

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_material_repair -v
```

Expected: current dedupe returns the old invalid item without replacing it.

- [ ] **Step 4: Implement local in-place repair**

Before selecting media by extension, validate every video candidate. When a matching old item is invalid, quarantine old files, copy/link the new valid file into the same material directory, preserve stable fields, update metadata, replace the item in the in-memory library, and save once.

- [ ] **Step 5: Implement central in-place repair**

When dedupe finds an old central item, validate its existing file. If invalid, fetch/copy the new node file into a temporary central path, validate it, quarantine old files, atomically replace, preserve the central ID, and persist one updated library item. Never change the old item if new validation fails.

- [ ] **Step 6: Run focused and full tests**

Expected: local and central repair tests pass; complete suite remains green.

- [ ] **Step 7: Create snapshot checkpoint**

Store modified files and hashes in the backup checkpoint.

---

### Task 5: Tesseract OCR Configuration and Runtime Behavior

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/requirements.deploy.txt`
- Create: `backend/.env.example`
- Modify: `backend/matrix_native_client.py`
- Modify: `tests/test_video_breakdown.py`

**Interfaces:**
- Consumes: system Tesseract and `pytesseract`/`Pillow`.
- Produces: `_ocr_breakdown_frames(frames) -> {'status', 'text', 'message', 'errors'}` with `ok`, `empty`, `partial`, `failed`, or `unavailable`.

- [ ] **Step 1: Write failing OCR tests**

Mock one successful frame and one exception to assert `partial`. Mock missing dependencies to assert `unavailable`. Use the installed engine with a generated Chinese image for an integration smoke assertion.

- [ ] **Step 2: Run tests and verify RED**

Expected: current implementation reports only `ok`, `empty`, or `disabled` and ignores configured language/options.

- [ ] **Step 3: Pin dependencies and add environment template**

Add exactly:

```text
Pillow==11.3.0
pytesseract==0.3.13
```

Add non-secret environment defaults from the approved spec to `backend/.env.example`.

- [ ] **Step 4: Implement configured OCR statuses**

Read `VIDEO_OCR_LANG` and `VIDEO_OCR_CONFIG`; collect per-frame errors with timestamps and stable error codes. Log exceptions as redacted JSON. Do not include OCR image bytes in logs.

- [ ] **Step 5: Verify OCR tests and live engine**

Run focused tests and verify `tesseract --list-langs` contains `chi_sim` and `eng`.

- [ ] **Step 6: Create snapshot checkpoint**

Store requirements, env template, client changes, tests, and hashes.

---

### Task 6: Chunked LK888 Gemini Transcription

**Files:**
- Create: `backend/utils/video_transcription.py`
- Create: `tests/test_video_transcription.py`
- Modify: `backend/matrix_native_client.py`

**Interfaces:**
- Produces: `export_audio_chunks(video_path, out_dir, chunk_sec=60, max_sec=600, ffmpeg_exe=None) -> dict`
- Produces: `validate_transcription_response(value: object) -> dict`
- Produces: `merge_transcription_segments(chunks: list[dict]) -> dict`
- Produces: `transcribe_audio_chunks(chunks, base_url, api_key, model, timeout, retries, proxies=None, only_ranges=None, progress=None) -> dict`
- Produces: `_transcribe_breakdown_audio(video_path, out_dir=None, only_ranges=None, progress=None) -> dict`

- [ ] **Step 1: Write failing chunking tests**

Generate a 125-second synthetic audio source or mock ffmpeg calls. Assert chunk ranges are `0-60`, `60-120`, and `120-125`; assert a source over 600 seconds is marked `truncated` and no chunk starts at or after 600.

- [ ] **Step 2: Write failing schema and timestamp tests**

Assert strict response acceptance for:

```json
{"language":"zh-CN","segments":[{"startSec":1.5,"endSec":4.0,"text":"测试"}]}
```

Reject unknown fields, negative times, `endSec < startSec`, empty text, and times over 60. Assert chunk offset 120 produces global `121.5-124.0`.

- [ ] **Step 3: Write failing remote/degradation tests**

Inject a fake request function. Assert Authorization uses the session token passed by `lk888_config()` but logs never contain it. Assert two retries, `partial` state, failed-range retention, and `only_ranges` retries only failed chunks.

- [ ] **Step 4: Run tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_video_transcription -v
```

Expected: utility module is missing.

- [ ] **Step 5: Implement MP3 chunk export**

Use ffmpeg with:

```text
-vn -ac 1 -ar 16000 -b:a 64k -ss <start> -t <duration> chunk_<start>.mp3
```

Process chunks sequentially and clean each Base64 value immediately after request construction. Never hold all encoded chunks in memory.

- [ ] **Step 6: Implement Gemini request and strict response parsing**

POST to:

```text
{base_url}/v1beta/models/{model}:generateContent
```

Body contains a transcription instruction and one `inline_data` audio part. Parse candidate text, remove an optional Markdown JSON fence, validate the fixed schema, and use a coarse chunk-level segment if JSON parsing or validation fails but non-empty text exists.

- [ ] **Step 7: Integrate native-client wrapper**

Replace the disabled placeholder with a wrapper that reads the approved environment values, uses `lk888_config()` and `_lk_proxies()`, returns `ok`/`partial`/`failed`/`no_audio`/`truncated`, and exposes failed ranges for retry.

- [ ] **Step 8: Run focused, smoke, and full tests**

Run unit tests, then the one-second real Gemini smoke. Expected: non-empty transcript and no secret leakage.

- [ ] **Step 9: Create snapshot checkpoint**

Store utility, client, tests, and updated hashes.

---

### Task 7: UI Retry, Reporting, Documentation, and End-to-End Verification

**Files:**
- Modify: `backend/matrix_native_client.py`
- Modify: `tests/test_video_breakdown.py`
- Create: `docs/ARCHITECTURE.md`
- Create: `docs/API_REFERENCE.md`
- Create: `docs/DEPLOYMENT.md`
- Create: `docs/IMPLEMENTATION.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Create or modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: validation, OCR, transcription, repair metadata.
- Produces: preflight-blocked invalid media, visible transcription statuses, failed-range retry button, updated Markdown report, complete operational documentation.

- [ ] **Step 1: Write failing UI/report tests**

Assert source contains a `重试转写` button and handler. Add pure-helper assertions that report Markdown includes duration, dimensions, OCR state, transcription state, truncation notice, failed ranges, retry count, and error IDs.

- [ ] **Step 2: Run tests and verify RED**

Expected: retry UI and enhanced report fields are missing.

- [ ] **Step 3: Add media preflight and retry state**

Before starting analysis, call `validate_video_file()`. Invalid media stops before frame extraction and shows a structured code/errorId. Store successful OCR/visual state plus failed transcription ranges in page memory. Enable retry only for `partial` or `failed`; retry calls transcription with `only_ranges` and regenerates the report without repeating download, frame extraction, or OCR.

- [ ] **Step 4: Clean temporary files safely**

Keep only the source video and in-memory report. Remove frame/audio temporary directories after report generation; for retry, recreate only requested MP3 ranges from the source video.

- [ ] **Step 5: Update four-level docs and changelog**

Document architecture/data flow, environment variables and Homebrew dependencies, unchanged public API surface, smoke failures, error-code lookup, backup/restore commands, and rollback. After all code edits, calculate actual line numbers and write `path/to/file.py#Lx-Ly` references in `docs/IMPLEMENTATION.md`.

- [ ] **Step 6: Run complete verification**

Run:

```bash
.venv/bin/python -m unittest discover tests -v
.venv/bin/python -m py_compile backend/utils/media_validation.py backend/utils/structured_log.py backend/utils/video_transcription.py backend/utils/data_util.py backend/api_server.py backend/central_server.py backend/matrix_native_client.py
```

Expected: all tests pass and syntax checks produce no output.

- [ ] **Step 7: Run real end-to-end repair**

Use the original Douyin URL. Verify:

- downloaded file is `video/mp4`, larger than the old HTML, and ffmpeg-readable;
- local material ID remains `6b52a85093b64245880cc2b47ddccd9f`;
- matching central material ID remains unchanged;
- old HTML exists in the 7-day quarantine path;
- report contains real metadata, frame analysis, OCR status, and timestamped transcription;
- no invalid new material record exists.

- [ ] **Step 8: Restart services and verify health**

Restart the center on `127.0.0.1:9080` and the native client with the existing Python.app launch method. Verify center process, client process, local engine `127.0.0.1:9081`, and one authenticated status request.

- [ ] **Step 9: Final snapshot and rollback rehearsal**

Create a final SHA256 manifest, compare it with the initial snapshot, and verify the documented restore commands can identify every changed file. Do not actually roll back successful code or repaired media.
