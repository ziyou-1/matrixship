# 视频替换共享服务 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox ("- [ ]") syntax for tracking.

**Goal:** 把本地客户端完整视频替换链路抽取为 Qt 和 /replacement 网页共用的本地服务，支持 handoff 和直接视频链接两种入口，并保留可验证、可恢复、可回滚的生产链路。

**Architecture:** 新增无 Qt 依赖的 replacement_service.py 作为任务生命周期边界，把源视频分析和两条生成流水线通过纯 Python 模块和注入适配器隔离。网页 API 和 Qt 页面都只调用服务边界，job.json 作为跨进程事实源；legacy/shared 开关保留旧 Qt 回滚路径。

**Tech Stack:** Python stdlib、现有 http.server 本地 API、现有下载/媒体校验/ffmpeg、LK888/ComicProject 适配器、unittest、OpenAPI YAML、JSON 结构化日志。

## Global Constraints

- 同时支持 hybrid_v2 和 comic_project 两条现有视频替换链路。
- 不把 provider 调用放入浏览器，不把视频任务迁移到中心服。
- job.json 是 Qt 与网页共用的唯一任务事实源，写入必须原子化并支持重启恢复。
- provider 提交成功不等于视频生成成功；必须完成终态确认、媒体下载和文件校验。
- 恢复时先查询既有 provider task；未确认原任务无有效结果时禁止新提交。
- 不预扣费，不按异步提交响应扣费，只按最终实际费用结算，billing ref 幂等。
- 日志只记录脱敏 job ID、阶段、模型、错误编号和 provider task 哈希，不记录 Token、Cookie、绝对路径或完整签名 URL。
- 网页继续受 MATRIX_REPLACEMENT_WEB_ENABLED 控制，服务使用 VIDEO_REPLACEMENT_SERVICE_MODE=legacy|shared。
- 同一用户本机同时最多一个视频替换 job；Qt 和网页共享跨进程锁。
- 图片单文件默认不超过 20 MB；provider 输入必须为可访问 HTTPS 媒体地址，禁止本地路径和 data:image。
- 不新增常驻端口、GPU 服务或数据库表；更新 OpenAPI、API、部署、排障、实现、CHANGELOG 和 migration.sql 的无迁移说明。
- 任何完整实现代码前，先完成 Task 1 的 fake 端到端冒烟骨架。

## File Boundaries

- Create: backend/replacement_service.py。公共 service facade、状态机、文件锁、worker、恢复、取消、重试、合成和安全响应。
- Create: backend/replacement_analysis.py。链接下载、媒体校验、抽帧/OCR/转写/视觉分析和报告的无 Qt 边界。
- Create: backend/replacement_pipeline.py。hybrid_v2 和 comic_project 的 provider 编排、恢复、回退、质检和计费。
- Modify: backend/replacement_web.py。视频页面、multipart 校验、脱敏响应和 API 适配；图文行为保持兼容。
- Modify: backend/api_server.py。prepare/execute/job/retry/concat/cancel 路由和边界日志。
- Modify: backend/matrix_native_client.py。Qt shared service adapter、legacy 开关和现有 BRIDGE 事件兼容。
- Create/Modify: tests/test_replacement_service.py、tests/test_replacement_web_mvp.py、tests/test_video_replacement.py、tests/test_video_replacement_v2.py。
- Modify: docs/openapi.yaml、docs/API_REFERENCE.md、docs/ARCHITECTURE.md、docs/DEPLOYMENT.md、docs/TROUBLESHOOTING.md、docs/IMPLEMENTATION.md、CHANGELOG.md、migration.sql。

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

## Task 5: Web API Lifecycle and Customer Page

**Files:**
- Modify: backend/replacement_service.py
- Modify: backend/replacement_web.py lines 40-392 and 721-809
- Modify: backend/api_server.py lines 7187-7334 and 7481-7497
- Modify: tests/test_replacement_web_mvp.py and tests/test_replacement_service.py

**Interfaces:**
- prepare_video_job(data_dir, fields, files) -> dict
- execute_video_job(data_dir, job_id, overrides) -> dict
- retry_video_job(data_dir, job_id, segment_indices) -> dict
- concat_video_job(data_dir, job_id) -> dict
- cancel_video_job(data_dir, job_id) -> dict
- video_job_response(job) -> dict, with no internal paths or credentials

- [ ] Step 1: Add failing tests for new routes, page controls and redacted responses.

Cover handoff prepare without sourceUrl, direct URL prepare, authenticated execute/retry/concat/cancel, job polling, invalid state 409, final media download and response redaction. Update HTML assertions for source mode, analysis progress, editable plan, execute, retry failed, cancel, concat and handoff status.

- [ ] Step 2: Run the web tests to establish the red state.

~~~powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp -v
~~~

- [ ] Step 3: Add service adapters and routes.

Use these routes:

~~~text
POST /api/replacement/video/prepare -> 202
POST /api/replacement/video/execute -> 202
GET  /api/replacement/video/job?jobId=... -> 200
POST /api/replacement/video/retry -> 202
POST /api/replacement/video/concat -> 202
POST /api/replacement/video/cancel -> 202
~~~

Keep the existing feature gate and Agent Token validation. Keep POST /api/replacement/video/start as a compatibility alias that cannot bypass plan confirmation. Validate task ID, filename and root for final media download.

- [ ] Step 4: Upgrade only the video portion of the page.

Use sessionStorage only for handoffId and jobId. Poll every 1 second during preparation and every 2 seconds during generation. Display safe progress, segment statuses, retry failed, cancel and final authenticated download. Do not change the note replacement flow.

- [ ] Step 5: Run API, OpenAPI and compile checks.

~~~powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp tests.test_openapi_contract -v
.\.venv-win\Scripts\python.exe -m py_compile backend\replacement_service.py backend\replacement_web.py backend\api_server.py tests\test_replacement_web_mvp.py
git diff --check
~~~

- [ ] Step 6: Commit the web lifecycle.

~~~powershell
git add backend/replacement_service.py backend/replacement_web.py backend/api_server.py tests/test_replacement_web_mvp.py tests/test_replacement_service.py
git commit -m "feat: run video replacement from local web service"
~~~

## Task 6: Qt Shared-Service Adapter and Rollback Switch

**Files:**
- Modify: backend/matrix_native_client.py lines 14406-16670
- Modify: tests/test_video_replacement.py, tests/test_video_replacement_v2.py and tests/test_replacement_service.py

**Interfaces:**
- ReplacementServiceAdapter.prepare/execute/retry/concat/cancel
- Existing video_replace_plan_ready, video_replace_progress, video_replace_done and comic frame events remain compatible.
- VIDEO_REPLACEMENT_SERVICE_MODE=legacy preserves the old path.

- [ ] Step 1: Add failing mode and adapter tests.

~~~python
def test_shared_mode_routes_qt_to_service(self):
    page = make_video_page_for_test()
    with patch.object(page.service, "prepare") as prepare, patch.object(page.service, "execute") as execute:
        page.generate_plan()
        page.start_generation()
    prepare.assert_called_once()
    execute.assert_called_once()

def test_legacy_mode_keeps_old_path(self):
    with patch.dict(os.environ, {"VIDEO_REPLACEMENT_SERVICE_MODE": "legacy"}):
        self.assertEqual(replacement_mode_for_new_job(), "legacy")
~~~

Also preserve one-person authorization, full-body validation, audio/subtitle validation, comic regeneration and concat event tests.

- [ ] Step 2: Run focused tests before wiring.

~~~powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement tests.test_video_replacement_v2 tests.test_replacement_service -v
~~~

Expected: new shared adapter tests fail before the page is wired.

- [ ] Step 3: Implement the adapter.

Build service requests from existing Qt controls, pass progress to BRIDGE.payload, read job state from disk, and never let Qt mutate provider task IDs or billing refs.

~~~python
if video_replacement_service_shared():
    self._service_adapter.execute(
        self._job["id"], overrides, progress=self._emit_service_progress
    )
else:
    self._legacy_start_generation()
~~~

- [ ] Step 4: Run native replacement tests and compile.

~~~powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_video_replacement tests.test_video_replacement_v2 tests.test_replacement_service -v
.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_video_replacement.py tests\test_video_replacement_v2.py
git diff --check
~~~

- [ ] Step 5: Commit the Qt adapter.

~~~powershell
git add backend/matrix_native_client.py tests/test_video_replacement.py tests/test_video_replacement_v2.py tests/test_replacement_service.py
git commit -m "feat: route native video replacement through shared service"
~~~

## Task 7: Observability, Circuit Breaker, Contracts and Docs

**Files:**
- Modify: backend/replacement_service.py, backend/replacement_web.py, backend/api_server.py and backend/platform_features.py
- Modify: tests/test_replacement_service.py and tests/test_replacement_web_mvp.py
- Modify: docs/openapi.yaml, docs/API_REFERENCE.md, docs/ARCHITECTURE.md, docs/DEPLOYMENT.md, docs/TROUBLESHOOTING.md, docs/IMPLEMENTATION.md, CHANGELOG.md and migration.sql

**Interfaces:**
- record_terminal_result(job) -> dict
- shared_mode_allowed() -> bool
- video_job_response(job) -> dict

- [ ] Step 1: Add failing circuit-breaker and redaction tests.

Use at least 100 terminal jobs with one failure and assert shared mode becomes legacy, while a secret-like provider URL and task ID do not appear in logs or API responses.

- [ ] Step 2: Run the red tests.

~~~powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service tests.test_replacement_web_mvp -v
~~~

- [ ] Step 3: Implement persisted terminal metrics and automatic switch.

Store a bounded result window under the agent data directory. Require at least 100 terminal jobs and switch new jobs to legacy only when failed / total is greater than 0.01. Do not interrupt an active job. Emit events for prepare_started, analysis_completed, provider_submitted, provider_recovered, billing_settled, video_completed, video_failed, shared_mode_circuit_opened and rollback_requested with redacted context.

- [ ] Step 4: Update OpenAPI and all required documents.

Document exact request fields, response schemas, 202/400/401/404/409/500 errors, feature flags, polling, source modes, local download route, restart requirement, circuit-breaker behavior, no database migration, stable-version rollback and current line references in docs/IMPLEMENTATION.md. Recalculate line numbers after all source edits and before commit.

- [ ] Step 5: Run contract and documentation checks.

~~~powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp tests.test_openapi_contract tests.test_replacement_service -v
git diff --check
rg -n "TODO|TBD|sourceVideoPath|Authorization|signed URL" docs/openapi.yaml docs/API_REFERENCE.md docs/DEPLOYMENT.md docs/TROUBLESHOOTING.md
~~~

Expected: no public schema exposes private paths or credentials, and no stale implementation line reference remains.

- [ ] Step 6: Commit only the Task 7 changes.

~~~powershell
git add backend tests docs CHANGELOG.md migration.sql
git commit -m "docs: document video replacement service rollout and rollback"
~~~

## Task 8: Full Verification and Release Evidence

**Files:**
- Modify only if a concrete verification failure requires it.
- Do not stage unrelated dirty files.

- [ ] Step 1: Run focused regression suites.

~~~powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_service -v
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp -v
.\.venv-win\Scripts\python.exe -m unittest tests.test_openapi_contract -v
.\.venv-win\Scripts\python.exe -m unittest tests.test_video_breakdown tests.test_video_replacement tests.test_video_replacement_v2 -v
~~~

Record exact counts only after commands finish.

- [ ] Step 2: Compile every changed Python module.

~~~powershell
.\.venv-win\Scripts\python.exe -m py_compile backend\replacement_service.py backend\replacement_analysis.py backend\replacement_pipeline.py backend\replacement_web.py backend\api_server.py backend\matrix_native_client.py tests\test_replacement_service.py tests\test_replacement_web_mvp.py
~~~

Expected: exit code 0.

- [ ] Step 3: Run a temporary-port HTTP smoke.

Start the local executor with MATRIX_REPLACEMENT_WEB_ENABLED=1, VIDEO_REPLACEMENT_SERVICE_MODE=shared, a temporary data directory and port 9092. Verify:

~~~text
GET /replacement -> 200 with video controls
GET /api/replacement/video/handoff?handoffId=VALID_HANDOFF_ID -> safe summary
POST /api/replacement/video/prepare -> 202 with rvw job ID
GET /api/replacement/video/job?jobId=JOB_ID -> sanitized state
POST /api/replacement/video/execute -> 202 in fake-provider mode
POST /api/replacement/video/concat -> 202 only after awaiting_review
~~~

Do not use the currently running 9081 process as proof until it is restarted with the new source. Do not print Agent Token or signed media URLs.

- [ ] Step 4: Run both acceptance paths.

Use one local fixture for direct-link resolution and one native-created handoff. Verify both reach planned, reopening the browser resumes the same job, and invalid source returns a structured error without false success.

- [ ] Step 5: Run live provider smoke only with explicit credentials and authorization.

Use one controlled account and short source. Store only task ID hashes, validate downloaded media and actual billing ref settlement, and stop on authentication, safety, captcha or account-lock conditions. Never report fake-provider output as live success.

- [ ] Step 6: Recalculate docs/IMPLEMENTATION.md line references and inspect final diff.

~~~powershell
git diff --check
git status --short
git diff --stat
rg -n "backend/(replacement_service|replacement_analysis|replacement_pipeline|replacement_web|api_server|matrix_native_client)\.py#L" docs/IMPLEMENTATION.md
~~~

Expected: only intended files are changed and all references point to current lines.

- [ ] Step 7: Record release evidence and commit.

Update CHANGELOG.md and docs/TROUBLESHOOTING.md with changed tiers, tests, smoke outcomes, restart requirement, no center/remote/database deployment, shared-to-legacy switch, previous stable installer/tag and residual live-provider risk. Then:

~~~powershell
git add backend tests docs CHANGELOG.md migration.sql
git commit -m "feat: complete shared local video replacement service"
~~~

## Plan Self-Review

- Spec coverage: Tasks 1-2 cover architecture and both source modes; Task 3 covers hybrid_v2; Task 4 covers comic recovery, fallback and actual billing; Task 5 covers web lifecycle; Task 6 covers Qt compatibility; Task 7 covers observability, OpenAPI, deployment, rollback and no migration; Task 8 covers release evidence.
- Placeholder scan: no unfinished marker or vague implementation step is used.
- Type consistency: ReplacementService methods are defined in Task 1 and consumed by Tasks 5-6; pipeline interfaces are defined in Tasks 3-4; circuit-breaker methods are defined and tested in Task 7.
- Safety review: no task authorizes remote deployment, database changes, live provider use without an explicit condition, or secret output.
- Documentation review: docs/IMPLEMENTATION.md line references are recalculated after source edits and before commit.
