# Task 2 Fix Brief: Redact Sensitive Note Inputs

## Findings To Fix

Task 2 reviewer found a Critical issue:

- `backend/replacement_web.py` passes user-controlled business fields and sanitized-but-untrusted filenames to the XHS smoke helper; its generated `copyCandidates` and `imageSlots` are persisted. Sensitive strings such as `Cookie=...`, `Authorization: Bearer ...`, and base64 image content embedded in a filename can survive into `job.json`.

Important test gap:

- Add adversarial note-job tests for sensitive business fields and filenames containing `data:image`, base64 payloads, `Cookie`, `Token`, and `Authorization`, then assert neither persisted jobs nor `job_response()` expose them.

## Scope

- Modify only `backend/replacement_web.py` and `tests/test_replacement_web_mvp.py`.
- Do not modify routes, docs, OpenAPI, changelog, migration, or unrelated files.
- Do not stage or commit.

## Requirements

- Add a failing test first.
- Redact or neutralize sensitive words and payload-shaped values before they reach persisted `job.json`.
- Persisted note jobs and `job_response()` must not contain:
  - `Cookie`
  - `Token`
  - `Authorization`
  - `Bearer`
  - `data:image`
  - obvious base64 payload fragments from malicious filenames or business fields.
- Keep normal Chinese business copy usable after redaction.
- Preserve existing successful tests.

## Verification

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp.ReplacementWebModuleTests -v
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp -v
.\.venv-win\Scripts\python.exe -m py_compile backend/replacement_web.py tests/test_replacement_web_mvp.py
```

Report RED and GREEN evidence in the Task 2 report file by appending a fix section.
