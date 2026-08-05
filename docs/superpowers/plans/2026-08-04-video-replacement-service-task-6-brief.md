# Task 6 Implementer Brief — Qt Shared-Service Adapter & Rollback Switch

You are the Task 6 implementer for the MatrixShip video-replacement-service refactor.
Workspace: `E:\Desktop\矩阵星舰_应用前后端与中心服源码_clean_20260710_150252`
Windows; venv python `.\.venv-win\Scripts\python.exe` (Bash tool: `.venv-win/Scripts/python.exe`).

## Read first
- Plan: `docs/superpowers/plans/2026-08-04-video-replacement-service.md` — implement **Task 6 only** (plan section "Task 6: Qt Shared-Service Adapter and Rollback Switch"). Do NOT do Task 7/8.
- Design: `docs/superpowers/specs/2026-08-04-video-replacement-service-design.md`
- Task 5 (already implemented, uncommitted, in the working tree): `backend/replacement_web.py` now has `build_video_service`, `_build_source_resolver`, `_build_pipeline`, `_SourceDownloader`; `backend/replacement_service.py` has `ReplacementService` (prepare/execute/retry/concat/cancel/get_job) + module-level `public_job`; `backend/replacement_pipeline.py` has `HybridReplacementPipeline` + `ComicProjectReplacementPipeline` + `settle_actual_cost`.
- Native helpers that already exist in `backend/matrix_native_client.py`: `_replacement_hybrid_pipeline()`, `_replacement_comic_pipeline()`, `_transcribe_breakdown_audio`, `_breakdown_source_validation`, `_extract_breakdown_frames`, `_ocr_breakdown_frames`, `_wf_download(url, path)`, `download_media(url, path)`, `_workflow_analyze_reference_video`.

## Scope (Task 6)
1. **Rollback switch** in `backend/matrix_native_client.py`:
   - `VIDEO_REPLACEMENT_SERVICE_MODE` env = `legacy` | `shared` (default `legacy` for safety unless the plan/design says otherwise — confirm against design; if design says shared-by-default with circuit fallback, keep default `legacy` here and let Task 7's circuit breaker own promotion).
   - `replacement_mode_for_new_job() -> "legacy"|"shared"` and `video_replacement_service_shared() -> bool`.
   - `legacy` mode preserves the existing Qt generation path byte-for-byte behavior.

2. **`ReplacementServiceAdapter`** (new, in matrix_native_client.py): `prepare/execute/retry/concat/cancel` that construct requests from existing Qt page controls, call the shared `ReplacementService` (via `replacement_web.build_video_service(data_dir)` or a direct `ReplacementService` build), read job state from disk (job.json is the source of truth), and emit existing BRIDGE progress. In shared mode `VideoReplacementPage` routes generation through the adapter; in legacy mode it keeps `_legacy_start_generation()`.

3. **Close the Task 5 direct-URL deviation**: add a native download entry point named `_replacement_web_download_source(source_url, job_dir)` (the name `_SourceDownloader.download` already probes) that reuses the existing breakdown/reference download path (`_wf_download` / `download_media` / the same downloader `_workflow_analyze_reference_video` uses) and returns the local video path. Validate media via `_breakdown_source_validation`. This makes production direct-URL prepare work.

## Hard constraints (matrixship-production-guard)
- Qt must NEVER mutate provider task IDs or billing refs; those live in job.json / pipeline only.
- Preserve existing BRIDGE events and their payload shape: `video_replace_plan_ready`, `video_replace_progress`, `video_replace_done`, and comic start/end-frame + video events. Existing subscribers must keep working.
- Preserve one-person (single-protagonist) authorization, full-body validation, audio/subtitle validation, comic frame regeneration, and concat event behavior — all existing tests for these must stay green.
- Provider submit success != generation success. Recovery-before-resubmit and final actual-cost idempotent billing already live in the pipeline; do NOT duplicate or bypass them.
- No remote deployment, no DB, no new resident port/GPU.
- Never log Token/Cookie/Authorization/signed URLs/absolute paths/raw media bytes.

## TDD (required)
1. Write FAILING tests first in `tests/test_video_replacement.py` / `tests/test_video_replacement_v2.py` / `tests/test_replacement_service.py`:
   - `test_shared_mode_routes_qt_to_service` (shared mode calls adapter.execute with job id + overrides + progress),
   - `test_legacy_mode_keeps_old_path` (`replacement_mode_for_new_job()=="legacy"` under `VIDEO_REPLACEMENT_SERVICE_MODE=legacy`),
   - adapter prepare/execute/retry/concat/cancel map to service and emit BRIDGE progress without exposing internal paths,
   - direct-URL download entry point returns a validated local path and rejects invalid media,
   - plus keep the existing one-person/full-body/audio/subtitle/comic/concat tests green.
2. Run focused red: `.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement tests.test_video_replacement_v2 tests.test_replacement_service -v`
3. Implement to GREEN.
4. `py_compile backend\matrix_native_client.py backend\replacement_web.py tests\test_video_replacement.py tests\test_video_replacement_v2.py`; `git diff --check`.

## Do NOT
- Do NOT commit / stage / move HEAD / touch unrelated dirty files.
- Do NOT edit `docs/IMPLEMENTATION.md` line numbers (controller recalculates in Task 7).
- Do NOT implement Task 7 (circuit breaker/observability/docs) or Task 8.
- Do NOT change the note-replacement flow or the web page note tab.

## Report back
- New symbols (adapter class, mode helpers, native download entry point) with file:line.
- Test names added + GREEN counts for the three suites.
- Confirm BRIDGE event shapes unchanged and legacy path preserved.
- Confirm production direct-URL prepare now works (deviation closed).
- Confirm no commit, no unrelated files, IMPLEMENTATION.md untouched.
