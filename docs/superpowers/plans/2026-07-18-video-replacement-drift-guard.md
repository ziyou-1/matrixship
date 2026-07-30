# Video Replacement Drift Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add project-level drift protection to video replacement so uploaded person images lock identity only, source video category/role/structure stay dominant, severe off-topic generations retry once and then block final composition.

**Architecture:** Keep the existing single-client PyQt/Python architecture and local JSON job persistence. Add small testable helpers in `backend/matrix_native_client.py` for drift guard config, source context extraction, reference preflight, source-lock prompt text, severe visual drift QC, and one-shot retry. Wire them into `VideoReplacementPage.start_generation()`, `_build_replacement_prompt()`, `_build_hybrid_video_edit_request()`, `_run_replacement_segment_qc()`, `_run_hybrid_non_talking_segment()`, and `_run_hybrid_replacement_segment()`.

**Tech Stack:** Python 3.12, unittest, PyQt, local JSON replacement jobs, existing LK888 media and vision proxy, existing structured JSON logging.

## Global Constraints

- Do not hardcode API keys, tokens, database URLs, or provider secrets.
- Keep all new behavior configurable and rollbackable with environment variables.
- Keep single-client video replacement concurrency at 1.
- First version must not add a local GPU model or increase local VRAM usage.
- Severe drift blocks `fast`, `standard`, and `high` modes.
- Person references are identity-only; source video category, subject role, product category, scene type, and marketing structure win when references conflict.
- Severe drift retries at most once per segment.
- Media validity and audio validity remain hard gates.
- Ordinary `face_mismatch`, `product_mismatch`, and `scene_mismatch` remain review warnings unless existing strict QC is explicitly enabled.
- Every blocker, retry, and degraded vision service path must be traceable in `replacement_job.json` and structured logs.
- After code changes, update `docs/IMPLEMENTATION.md` with recalculated `path#Lx-Ly` line references before any git commit.
- The current clean export may not contain `.git`; commit steps apply only when executing inside the real repo/worktree.

---

## Files And Responsibilities

- Modify: `backend/matrix_native_client.py`
  - Add drift guard config helpers.
  - Extract source category/role/product context from existing breakdown analysis.
  - Run reference preflight through existing `lk888_vision`.
  - Add source-lock prompt text.
  - Extend visual QC schema and hard-block severe drift.
  - Add one-shot severe drift retry for talking and non-talking segments.
  - Surface drift status in segment status text and job JSON.
- Modify: `tests/test_video_replacement_v2.py`
  - Add focused unit tests for config, preflight parsing, prompt locks, QC hard gate, retry behavior, rollback switches, and job JSON fields.
- Modify: `docs/ARCHITECTURE.md`
  - Document the three-layer drift guard flow.
- Modify: `docs/API_REFERENCE.md`
  - Document new job/segment JSON fields and error codes.
- Modify: `docs/DEPLOYMENT.md`
  - Document environment variables and rollback switches.
- Modify: `docs/TROUBLESHOOTING.md`
  - Document diagnosis and operator actions for `reference_mismatch`, `visual_drift_blocked`, and `visual_drift_retry_exhausted`.
- Modify: `docs/IMPLEMENTATION.md`
  - Recalculate line references for modified implementation and tests.
- Modify: `CHANGELOG.md`
  - Add release notes and operations notes.
- Modify: `migration.sql`
  - Keep no-op migration statement for release traceability because this change has no DB schema migration.

---

### Task 1: Smoke Reproducer And Drift Guard Config

**Files:**
- Modify: `tests/test_video_replacement_v2.py`
- Modify: `backend/matrix_native_client.py`

**Interfaces:**
- Produces: `_replacement_drift_guard_enabled(job=None) -> bool`
- Produces: `_replacement_reference_preflight_enabled(job=None) -> bool`
- Produces: `_replacement_block_severe_drift(job=None) -> bool`
- Produces: `_replacement_drift_auto_retry_enabled(job=None) -> bool`
- Produces: `_replacement_drift_max_retries(job=None) -> int`
- Produces: `_replacement_drift_guard_config(job=None) -> dict`
- Produces: `_replacement_source_context_from_analysis(analysis=None) -> dict`

- [ ] **Step 1: Write failing smoke/config tests**

Add these tests near the existing identity-mode tests in `tests/test_video_replacement_v2.py`:

```python
    def test_drift_guard_config_defaults_are_production_safe(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            job = {}

            config = self.client._replacement_drift_guard_config(job)

        self.assertTrue(config["enabled"])
        self.assertTrue(config["preflightEnabled"])
        self.assertTrue(config["blockSevereDrift"])
        self.assertTrue(config["autoRetry"])
        self.assertEqual(config["maxRetries"], 1)

    def test_drift_guard_can_be_disabled_by_env(self):
        with mock.patch.dict(os.environ, {"VIDEO_REPLACE_DRIFT_GUARD": "0"}):
            job = {}

            self.assertFalse(self.client._replacement_drift_guard_enabled(job))
            self.assertFalse(self.client._replacement_reference_preflight_enabled(job))
            self.assertFalse(self.client._replacement_block_severe_drift(job))
            self.assertFalse(self.client._replacement_drift_auto_retry_enabled(job))

    def test_source_context_extracts_category_role_and_product(self):
        analysis = {
            "visual": "丰田门店里，一名男销售顾问介绍蓝牌新能源凯美瑞和赛那。",
            "frameNotes": "多帧出现汽车展厅、白色轿车、销售讲解。",
            "ocr": {"text": "蓝牌新能源 凯美瑞 广汽丰田"},
            "transcript": {"text": "老板你看这台蓝牌新能源车。"},
        }

        context = self.client._replacement_source_context_from_analysis(analysis)

        self.assertIn("丰田", context["evidence"])
        self.assertIn("汽车", context["sourceCategory"])
        self.assertIn("销售", context["sourceRole"])
        self.assertIn("汽车", context["sourceProductCategory"])
```

- [ ] **Step 2: Run focused tests and confirm they fail**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_drift_guard_config_defaults_are_production_safe \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_drift_guard_can_be_disabled_by_env \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_source_context_extracts_category_role_and_product -v
```

Expected: fail with `AttributeError` for missing helper functions.

- [ ] **Step 3: Implement config and source-context helpers**

Add the helpers after `_replacement_visual_qc_blocks()` in `backend/matrix_native_client.py`:

```python
def _replacement_drift_guard_enabled(job=None):
    job = job or {}
    value = job.get("driftGuardEnabled")
    if value is not None:
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    return _env_enabled("VIDEO_REPLACE_DRIFT_GUARD", "1")


def _replacement_reference_preflight_enabled(job=None):
    if not _replacement_drift_guard_enabled(job):
        return False
    job = job or {}
    value = job.get("referencePreflightEnabled")
    if value is not None:
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    return _env_enabled("VIDEO_REPLACE_REFERENCE_PREFLIGHT", "1")


def _replacement_block_severe_drift(job=None):
    if not _replacement_drift_guard_enabled(job):
        return False
    job = job or {}
    value = job.get("blockSevereDrift")
    if value is not None:
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    return _env_enabled("VIDEO_REPLACE_BLOCK_SEVERE_DRIFT", "1")


def _replacement_drift_auto_retry_enabled(job=None):
    if not _replacement_drift_guard_enabled(job):
        return False
    job = job or {}
    value = job.get("driftAutoRetry")
    if value is not None:
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    return _env_enabled("VIDEO_REPLACE_DRIFT_AUTO_RETRY", "1")


def _replacement_drift_max_retries(job=None):
    job = job or {}
    raw = job.get("driftMaxRetries")
    if raw is None:
        raw = os.getenv("VIDEO_REPLACE_DRIFT_MAX_RETRIES", "1")
    try:
        return max(0, min(3, int(raw)))
    except (TypeError, ValueError):
        return 1


def _replacement_drift_guard_config(job=None):
    return {
        "enabled": _replacement_drift_guard_enabled(job),
        "preflightEnabled": _replacement_reference_preflight_enabled(job),
        "blockSevereDrift": _replacement_block_severe_drift(job),
        "autoRetry": _replacement_drift_auto_retry_enabled(job),
        "maxRetries": _replacement_drift_max_retries(job),
    }
```

Add a conservative source-context extractor near `_replacement_excerpt()`:

```python
def _replacement_source_context_from_analysis(analysis=None):
    analysis = analysis or {}
    ocr = analysis.get("ocr") or {}
    transcript = analysis.get("transcript") or {}
    evidence = "\n".join([
        _replacement_excerpt(analysis.get("visual"), 500),
        _replacement_excerpt(analysis.get("frameNotes"), 500),
        _replacement_excerpt(ocr.get("text"), 300),
        _replacement_excerpt(transcript.get("text"), 400),
    ]).strip()
    lowered = evidence.lower()

    def pick_category():
        car_words = ("汽车", "车", "丰田", "凯美瑞", "赛那", "新能源", "4s", "展厅", "门店")
        beauty_words = ("美妆", "粉底", "口红", "护肤", "化妆", "彩妆")
        food_words = ("食品", "饮料", "零食", "餐饮")
        if any(word in lowered or word in evidence for word in car_words):
            return "汽车销售"
        if any(word in lowered or word in evidence for word in beauty_words):
            return "美妆带货"
        if any(word in lowered or word in evidence for word in food_words):
            return "食品带货"
        return "未知短视频"

    category = pick_category()
    role = "销售顾问" if any(word in evidence for word in ("销售", "顾问", "讲车", "介绍车")) else "视频人物"
    product = "汽车" if category == "汽车销售" else ("美妆产品" if category == "美妆带货" else "源视频产品")
    return {
        "sourceCategory": category,
        "sourceRole": role,
        "sourceProductCategory": product,
        "evidence": evidence,
    }
```

- [ ] **Step 4: Run focused tests and confirm they pass**

Run the same command from Step 2.

Expected: all three tests pass.

- [ ] **Step 5: Commit or record no-git status**

If executing in a git worktree:

```bash
git add backend/matrix_native_client.py tests/test_video_replacement_v2.py
git commit -m "feat: add video replacement drift guard config"
```

If executing in this clean export without `.git`, record `git rev-parse --show-toplevel` output in the task report and do not fabricate a commit.

---

### Task 2: Reference Preflight Before Remote Video Cost

**Files:**
- Modify: `tests/test_video_replacement_v2.py`
- Modify: `backend/matrix_native_client.py`

**Interfaces:**
- Consumes: `_replacement_drift_guard_config(job=None) -> dict`
- Consumes: `_replacement_source_context_from_analysis(analysis=None) -> dict`
- Produces: `_run_replacement_reference_preflight(job) -> dict`
- Produces: `_replacement_reference_preflight_blocks(job, preflight) -> bool`

- [ ] **Step 1: Write failing preflight tests**

Add:

```python
    def test_reference_preflight_warns_for_face_context_mismatch(self):
        job = {
            "breakdownAnalysis": {"visual": "汽车展厅男销售介绍丰田新能源车"},
            "productImageUrls": ["https://x/car.png"],
            "faceSourceUrls": ["https://x/beauty-face.png"],
            "sceneImageUrl": "https://x/showroom.png",
            "noPersonMode": False,
        }
        raw = (
            '{"ok":true,"severity":"warning","blocked":false,'
            '"sourceCategory":"汽车销售","sourceRole":"销售顾问",'
            '"sourceProductCategory":"汽车",'
            '"referenceRisks":[{"type":"face_context_mismatch","url":"https://x/beauty-face.png","reason":"美妆主播上下文"}],'
            '"reason":"人物图只作为身份参考"}'
        )

        with mock.patch.object(self.client, "lk888_vision", return_value=raw):
            result = self.client._run_replacement_reference_preflight(job)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "warning")
        self.assertFalse(result["blocked"])
        self.assertEqual(result["referenceRisks"][0]["type"], "face_context_mismatch")

    def test_reference_preflight_blocks_product_category_mismatch(self):
        job = {
            "breakdownAnalysis": {"visual": "汽车展厅男销售介绍丰田新能源车"},
            "productImageUrls": ["https://x/lipstick.png"],
            "faceSourceUrls": ["https://x/face.png"],
            "sceneImageUrl": "https://x/showroom.png",
        }
        raw = (
            '{"ok":false,"severity":"blocking","blocked":true,'
            '"sourceCategory":"汽车销售","sourceRole":"销售顾问",'
            '"sourceProductCategory":"汽车",'
            '"referenceRisks":[{"type":"product_category_mismatch","url":"https://x/lipstick.png","reason":"产品图是美妆"}],'
            '"reason":"产品图与源视频产品类别冲突"}'
        )

        with mock.patch.object(self.client, "lk888_vision", return_value=raw):
            result = self.client._run_replacement_reference_preflight(job)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(self.client._replacement_reference_preflight_blocks(job, result))
        self.assertEqual(result["code"], "reference_mismatch")

    def test_reference_preflight_degrades_when_vision_service_fails(self):
        job = {
            "breakdownAnalysis": {"visual": "汽车展厅男销售介绍丰田新能源车"},
            "productImageUrls": ["https://x/car.png"],
        }

        with mock.patch.object(self.client, "lk888_vision", side_effect=RuntimeError("timeout")), \
                mock.patch.object(self.client, "_replacement_error_id", return_value="err-preflight"):
            result = self.client._run_replacement_reference_preflight(job)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(result["errorId"], "err-preflight")
```

- [ ] **Step 2: Run focused tests and confirm they fail**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_reference_preflight_warns_for_face_context_mismatch \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_reference_preflight_blocks_product_category_mismatch \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_reference_preflight_degrades_when_vision_service_fails -v
```

Expected: fail with missing preflight helpers.

- [ ] **Step 3: Implement reference preflight helpers**

Add near `_run_replacement_visual_qc()`:

```python
def _replacement_reference_preflight_blocks(job, preflight):
    if not _replacement_reference_preflight_enabled(job):
        return False
    preflight = preflight or {}
    if preflight.get("blocked") is True:
        return True
    return str(preflight.get("status") or "").strip().lower() == "blocked"


def _run_replacement_reference_preflight(job):
    import json as _json
    import re as _re
    job = job or {}
    if not _replacement_reference_preflight_enabled(job):
        return {"ok": True, "status": "skipped", "blocked": False, "referenceRisks": []}
    context = _replacement_source_context_from_analysis(job.get("breakdownAnalysis") or {})
    media_urls = []
    media_urls.extend(job.get("productImageUrls") or [])
    if not _replacement_no_person_mode(job):
        media_urls.extend(job.get("faceSourceUrls") or [])
        if job.get("modelFaceUrl"):
            media_urls.append(job.get("modelFaceUrl"))
    if job.get("sceneImageUrl"):
        media_urls.append(job.get("sceneImageUrl"))
    media_urls = [str(url).strip() for url in media_urls if str(url).strip()]
    prompt = (
        "你是短视频同款替换的参考图预检器。源视频类别、人物角色、产品类别和镜头结构优先。"
        "人物参考图只允许作为脸、发型、外貌参考，不允许继承其中的行业、商品、直播间、背景或道具。"
        "产品图如果与源视频产品类别明显冲突必须 blocked=true。"
        "仅输出 JSON："
        '{"ok":true或false,"severity":"passed|warning|blocking","blocked":true或false,'
        '"sourceCategory":"类别","sourceRole":"角色","sourceProductCategory":"产品类别",'
        '"referenceRisks":[{"type":"风险类型","url":"媒体URL","reason":"原因"}],"reason":"简短原因"}。'
        "源视频证据：%s；推断：%s/%s/%s"
        % (
            _replacement_excerpt(context.get("evidence"), 900),
            context.get("sourceCategory") or "",
            context.get("sourceRole") or "",
            context.get("sourceProductCategory") or "",
        )
    )
    try:
        raw = lk888_vision(prompt, media_urls, max_tokens=700)
        match = _re.search(r"\{[\s\S]*\}", str(raw or ""))
        if not match:
            raise RuntimeError("reference_preflight_invalid_response")
        parsed = _json.loads(match.group(0))
    except Exception as exc:
        error_id = _replacement_error_id(
            "video_replace_reference_preflight_failed",
            exc,
            source_video=job.get("sourceVideoPath") or "",
        )
        return {
            "ok": True,
            "status": "deferred",
            "blocked": False,
            "code": "reference_preflight_deferred",
            "errorId": error_id,
            "referenceRisks": [],
            "reason": "参考图预检服务异常，已降级为后置质检",
            **context,
        }
    blocked = parsed.get("blocked") is True or str(parsed.get("severity") or "").lower() == "blocking"
    status = "blocked" if blocked else ("warning" if str(parsed.get("severity") or "").lower() == "warning" else "passed")
    return {
        "ok": not blocked,
        "status": status,
        "blocked": blocked,
        "code": "reference_mismatch" if blocked else "ok",
        "sourceCategory": str(parsed.get("sourceCategory") or context.get("sourceCategory") or ""),
        "sourceRole": str(parsed.get("sourceRole") or context.get("sourceRole") or ""),
        "sourceProductCategory": str(parsed.get("sourceProductCategory") or context.get("sourceProductCategory") or ""),
        "referenceRisks": list(parsed.get("referenceRisks") or []),
        "reason": str(parsed.get("reason") or "")[:240],
    }
```

- [ ] **Step 4: Wire preflight into `start_generation()` after `_build_job()` and before segment execution**

Inside the `work()` closure in `VideoReplacementPage.start_generation()`, immediately after `job = self._build_job()` and `self._job = job`, add:

```python
                job["driftGuardConfig"] = _replacement_drift_guard_config(job)
                preflight = _run_replacement_reference_preflight(job)
                job["referencePreflight"] = preflight
                _save_replacement_job(job)
                if _replacement_reference_preflight_blocks(job, preflight):
                    error_id = _replacement_error_id(
                        "video_replace_reference_preflight_blocked",
                        RuntimeError(preflight.get("code") or "reference_mismatch"),
                        source_video=job.get("sourceVideoPath") or "",
                    )
                    job.update({
                        "status": "failed",
                        "error": preflight.get("reason") or "参考图与源视频主题冲突",
                        "errorId": error_id,
                    })
                    BRIDGE.payload.emit("video_replace_done", {
                        "jobId": job["id"],
                        "message": "参考图与原视频主题冲突，已停止生成（错误编号 %s）" % (error_id or "-"),
                        "job": job,
                    })
                    return
```

- [ ] **Step 5: Run focused tests and a syntax check**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_reference_preflight_warns_for_face_context_mismatch \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_reference_preflight_blocks_product_category_mismatch \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_reference_preflight_degrades_when_vision_service_fails -v
.venv/bin/python -m py_compile backend/matrix_native_client.py
```

Expected: focused tests and compile pass.

- [ ] **Step 6: Commit or record no-git status**

If executing in a git worktree:

```bash
git add backend/matrix_native_client.py tests/test_video_replacement_v2.py
git commit -m "feat: preflight video replacement references"
```

If no git metadata exists, record that no commit was possible.

---

### Task 3: Source-Lock Prompt And Identity-Only Reference Semantics

**Files:**
- Modify: `tests/test_video_replacement_v2.py`
- Modify: `backend/matrix_native_client.py`

**Interfaces:**
- Consumes: `_replacement_source_context_from_analysis(analysis=None) -> dict`
- Produces: `_replacement_source_lock_text(job_or_analysis=None) -> str`
- Produces: `_replacement_reference_retry_note(job=None, segment=None) -> str`

- [ ] **Step 1: Write failing prompt tests**

Add:

```python
    def test_replacement_prompt_contains_source_lock_and_identity_only_rule(self):
        analysis = {
            "visual": "丰田门店男销售介绍新能源车",
            "ocr": {"text": "广汽丰田 凯美瑞"},
            "transcript": {"text": "今天讲这台车"},
        }
        segment = {"index": 1, "start": 0, "end": 8}

        prompt = self.client._build_replacement_prompt(
            segment, analysis, "uploaded car product", "authorized beauty presenter face"
        )

        self.assertIn("Source lock", prompt)
        self.assertIn("Person references are identity-only", prompt)
        self.assertIn("source video category", prompt)
        self.assertIn("汽车", prompt)

    def test_hybrid_video_edit_prompt_preserves_source_category_over_face_context(self):
        job = {
            "breakdownAnalysis": {"visual": "汽车展厅男销售介绍丰田新能源车"},
            "productImageUrls": ["https://x/car.png"],
            "faceSourceUrls": ["https://x/beauty-face.png"],
            "modelFaceUrl": "https://x/beauty-face.png",
            "sceneImageUrl": "https://x/showroom.png",
            "referencePreflight": {
                "sourceCategory": "汽车销售",
                "sourceRole": "销售顾问",
                "sourceProductCategory": "汽车",
                "referenceRisks": [{"type": "face_context_mismatch", "reason": "美妆主播上下文"}],
            },
        }
        segment = {"duration": 8, "prompt": "base prompt"}

        _model, payload = self.client._build_hybrid_video_edit_request(job, segment, "https://x/source.mp4")

        self.assertIn("Source lock", payload["prompt"])
        self.assertIn("identity-only", payload["prompt"])
        self.assertIn("汽车销售", payload["prompt"])
        self.assertIn("If references conflict", payload["prompt"])
```

- [ ] **Step 2: Run focused tests and confirm they fail**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_replacement_prompt_contains_source_lock_and_identity_only_rule \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_hybrid_video_edit_prompt_preserves_source_category_over_face_context -v
```

Expected: fail because source-lock text is not in prompts.

- [ ] **Step 3: Implement source-lock helper**

Add near `_build_replacement_prompt()`:

```python
def _replacement_source_lock_text(job_or_analysis=None):
    value = job_or_analysis or {}
    if "breakdownAnalysis" in value or "referencePreflight" in value:
        preflight = value.get("referencePreflight") or {}
        context = _replacement_source_context_from_analysis(value.get("breakdownAnalysis") or {})
        source_category = preflight.get("sourceCategory") or context.get("sourceCategory") or "source video category"
        source_role = preflight.get("sourceRole") or context.get("sourceRole") or "source subject role"
        source_product = preflight.get("sourceProductCategory") or context.get("sourceProductCategory") or "source product category"
    else:
        context = _replacement_source_context_from_analysis(value)
        source_category = context.get("sourceCategory") or "source video category"
        source_role = context.get("sourceRole") or "source subject role"
        source_product = context.get("sourceProductCategory") or "source product category"
    return (
        "Source lock:\n"
        "- Preserve original video category: %s.\n"
        "- Preserve original subject role: %s.\n"
        "- Preserve original product category: %s.\n"
        "- Preserve original scene type, camera rhythm, subject count and marketing structure.\n"
        "- Person references are identity-only references. Do not copy their product, industry, room, "
        "livestream setup, cosmetics, props, captions or background.\n"
        "- Product references control only the target product. Scene references control only environment.\n"
        "- If references conflict, source video category and uploaded product category win."
        % (source_category, source_role, source_product)
    )
```

Add:

```python
def _replacement_reference_retry_note(job=None, segment=None):
    job = job or {}
    segment = segment or {}
    if int(segment.get("driftRetryCount") or 0) <= 0:
        return ""
    risks = (job.get("referencePreflight") or {}).get("referenceRisks") or []
    risk_text = "; ".join(str(item.get("type") or "") for item in risks if isinstance(item, dict))
    return (
        "Drift retry: the previous generation changed topic or role. Strengthen source lock, "
        "treat person images as face identity only, and ignore risky reference context%s."
        % (": " + risk_text if risk_text else "")
    )
```

- [ ] **Step 4: Wire source lock into prompts**

In `_build_replacement_prompt()`, insert `_replacement_source_lock_text(analysis)` after the segment line and before product/model lines.

In `_build_replacement_keyframe_prompt()`, append `_replacement_source_lock_text(analysis)` before product/model notes.

In `_build_hybrid_video_edit_request()`, append `_replacement_source_lock_text(job)` and `_replacement_reference_retry_note(job, segment)` to the prompt list.

In `_run_replacement_segment()`, before `_build_replacement_video_prompt()`, prepend `_replacement_source_lock_text(job)` if the job contains `breakdownAnalysis`.

- [ ] **Step 5: Run focused tests**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_replacement_prompt_contains_source_lock_and_identity_only_rule \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_hybrid_video_edit_prompt_preserves_source_category_over_face_context -v
.venv/bin/python -m py_compile backend/matrix_native_client.py
```

Expected: focused tests and compile pass.

- [ ] **Step 6: Commit or record no-git status**

If executing in a git worktree:

```bash
git add backend/matrix_native_client.py tests/test_video_replacement_v2.py
git commit -m "feat: lock source context in replacement prompts"
```

If no git metadata exists, record that no commit was possible.

---

### Task 4: Severe Visual Drift QC Hard Gate

**Files:**
- Modify: `tests/test_video_replacement_v2.py`
- Modify: `backend/matrix_native_client.py`

**Interfaces:**
- Consumes: `_replacement_block_severe_drift(job=None) -> bool`
- Produces: `_replacement_is_severe_drift_code(code) -> bool`
- Produces: `visualDriftQc` segment/job QC payload

- [ ] **Step 1: Write failing severe drift QC tests**

Add:

```python
    def test_visual_qc_blocks_severe_topic_drift_in_all_identity_modes(self):
        response = (
            '{"sourceProductVisible":true,"faceMatch":true,"productMatch":true,'
            '"logoTextReadable":true,"sceneMatch":true,'
            '"topicMatch":false,"roleMatch":false,"structureMatch":false,'
            '"severeDrift":true,"reason":"汽车销售视频变成美妆主播化妆品近景"}'
        )
        for mode in ("fast", "standard", "high"):
            with self.subTest(mode=mode):
                job = {
                    "identityMode": mode,
                    "productImageUrls": ["https://x/car.png"],
                    "modelFaceUrl": "https://x/face.png",
                    "sceneImageUrl": "https://x/showroom.png",
                    "temporaryMaterialIds": [],
                }
                segment = {"index": 1}
                with mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/result.mp4", {})), \
                        mock.patch.object(self.client, "lk888_vision", return_value=response):
                    result = self.client._run_replacement_visual_qc(job, segment, "/tmp/result.mp4")

                self.assertFalse(result["ok"])
                self.assertEqual(result["code"], "visual_drift_blocked")
                self.assertTrue(result["visualDriftQc"]["severeDrift"])

    def test_visual_qc_keeps_regular_face_mismatch_as_review_warning_policy(self):
        job = {
            "identityMode": "standard",
            "productImageUrls": ["https://x/product.png"],
            "modelFaceUrl": "https://x/face.png",
            "temporaryMaterialIds": [],
        }
        segment = {"index": 1}
        response = (
            '{"sourceProductVisible":true,"faceMatch":false,"productMatch":true,'
            '"logoTextReadable":true,"sceneMatch":true,'
            '"topicMatch":true,"roleMatch":true,"structureMatch":true,'
            '"severeDrift":false,"reason":"脸不够像"}'
        )

        with mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/result.mp4", {})), \
                mock.patch.object(self.client, "lk888_vision", return_value=response), \
                mock.patch.object(self.client, "_breakdown_source_validation", return_value={"ok": True}), \
                mock.patch.object(self.client, "_replacement_audio_qc", return_value={"ok": True}), \
                mock.patch.object(self.client, "_extract_replacement_qc_frames", return_value=["a.jpg", "b.jpg", "c.jpg"]):
            result = self.client._run_replacement_segment_qc(job, segment, "/tmp/result.mp4")

        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "visual_qc_warning")
        self.assertEqual(segment["qcWarnings"][0]["severity"], "review_warning")
```

- [ ] **Step 2: Run focused tests and confirm they fail**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_visual_qc_blocks_severe_topic_drift_in_all_identity_modes \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_visual_qc_keeps_regular_face_mismatch_as_review_warning_policy -v
```

Expected: first test fails because current QC ignores `topicMatch`, `roleMatch`, `structureMatch`, and `severeDrift`.

- [ ] **Step 3: Extend visual QC prompt and parser**

In `_run_replacement_visual_qc()`, update the prompt JSON contract to include:

```text
"topicMatch":true或false,"roleMatch":true或false,"structureMatch":true或false,"severeDrift":true或false
```

Add prompt rules:

```text
topicMatch 要求待审核视频仍属于原视频行业和商品主题；roleMatch 要求人物角色仍符合原视频，例如汽车门店销售不能变成美妆主播；structureMatch 要求镜头结构和营销讲解结构没有严重改变；汽车讲解变成化妆品特写、食品带货或无关生活方式视频时 severeDrift 必须为 true。
```

After existing `checks` creation, add:

```python
    visual_drift = {
        "topicMatch": parsed.get("topicMatch") is not False,
        "roleMatch": parsed.get("roleMatch") is not False,
        "structureMatch": parsed.get("structureMatch") is not False,
        "severeDrift": parsed.get("severeDrift") is True,
        "reason": str(parsed.get("reason") or "")[:240],
    }
    if visual_drift["severeDrift"] or not visual_drift["topicMatch"]:
        code = "visual_drift_blocked"
    elif not visual_drift["roleMatch"]:
        code = "role_mismatch"
    elif not visual_drift["structureMatch"]:
        code = "structure_mismatch"
```

Keep existing product/face/scene mismatch code path below this severe-drift branch, so severe drift has priority.

Return `visualDriftQc`:

```python
    return {
        "ok": code == "ok",
        "code": code,
        "checks": checks,
        "visualDriftQc": visual_drift,
        "sourceProductVisible": bool(source_product_visible),
        "reason": str(parsed.get("reason") or "")[:240],
        "resultUrl": result_url,
    }
```

- [ ] **Step 4: Add severe drift gate in segment QC**

Add helper near `_replacement_qc_warning_severity()`:

```python
def _replacement_is_severe_drift_code(code):
    return str(code or "").strip() in (
        "visual_drift_blocked",
        "topic_mismatch",
        "role_mismatch",
        "structure_mismatch",
        "visual_drift_retry_exhausted",
    )
```

Update `_replacement_qc_warning_severity()` so severe drift returns `blocking`.

In `_run_replacement_segment_qc()`, when `not visual.get("ok")`, copy visual drift payload:

```python
            if visual.get("visualDriftQc"):
                segment["visualDriftQc"] = dict(visual.get("visualDriftQc") or {})
```

Then change the block decision:

```python
            if _replacement_is_severe_drift_code(warning["code"]) and _replacement_block_severe_drift(job):
                return {"ok": False, "code": warning["code"],
                        "audio": audio, "frames": frames, "visual": visual,
                        "warnings": [warning], "retryableDrift": True}
            if _replacement_visual_qc_blocks(job):
                return {"ok": False, "code": warning["code"],
                        "audio": audio, "frames": frames, "visual": visual,
                        "warnings": [warning]}
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_visual_qc_blocks_severe_topic_drift_in_all_identity_modes \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_visual_qc_keeps_regular_face_mismatch_as_review_warning_policy -v
.venv/bin/python -m py_compile backend/matrix_native_client.py
```

Expected: tests and compile pass.

- [ ] **Step 6: Commit or record no-git status**

If executing in a git worktree:

```bash
git add backend/matrix_native_client.py tests/test_video_replacement_v2.py
git commit -m "feat: block severe replacement visual drift"
```

If no git metadata exists, record that no commit was possible.

---

### Task 5: One-Shot Drift Retry And Segment Failure Semantics

**Files:**
- Modify: `tests/test_video_replacement_v2.py`
- Modify: `backend/matrix_native_client.py`

**Interfaces:**
- Consumes: `_replacement_is_severe_drift_code(code) -> bool`
- Consumes: `_replacement_drift_auto_retry_enabled(job=None) -> bool`
- Consumes: `_replacement_drift_max_retries(job=None) -> int`
- Produces: `_replacement_can_retry_drift(job, segment, qc=None) -> bool`
- Produces: `_replacement_mark_drift_retry(job, segment, qc=None) -> None`
- Produces: `_replacement_mark_drift_exhausted(segment, qc=None) -> None`

- [ ] **Step 1: Write failing retry tests**

Add:

```python
    def test_non_talking_segment_retries_once_on_severe_drift(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.mp4"
            edited = Path(td) / "edited.mp4"
            make_tone_video(self.client, source, duration=1)
            make_tone_video(self.client, edited, duration=1)
            job = {
                "id": "job-drift-retry",
                "identityMode": "standard",
                "outDir": td,
                "sourceVideoPath": str(source),
                "segments": [],
                "productImageUrls": ["https://x/car.png"],
                "modelFaceUrl": "https://x/face.png",
            }
            segment = {"index": 1, "start": 0, "end": 1, "duration": 1, "audioStatus": "pending", "qcStatus": "pending"}
            job["segments"] = [segment]
            qc_results = [
                {"ok": False, "code": "visual_drift_blocked", "frames": ["a", "b", "c"],
                 "checks": {"media": "passed", "audio": "passed"}, "retryableDrift": True,
                 "visual": {"visualDriftQc": {"severeDrift": True}}},
                {"ok": True, "code": "ok", "frames": ["a", "b", "c"],
                 "checks": {"media": "passed", "audio": "passed"}},
            ]

            with mock.patch.object(self.client, "_extract_replacement_segment", side_effect=lambda _src, _seg, out: shutil.copyfile(source, out)), \
                    mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/source.mp4", {})), \
                    mock.patch.object(self.client, "lk888_media_task", return_value="https://x/edited.mp4") as media_task, \
                    mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: shutil.copyfile(edited, path)), \
                    mock.patch.object(self.client, "_ensure_segment_audio", return_value=None), \
                    mock.patch.object(self.client, "_run_replacement_segment_qc", side_effect=qc_results), \
                    mock.patch.object(self.client, "_save_replacement_job", return_value=str(Path(td) / "replacement_job.json")):
                path = self.client._run_hybrid_non_talking_segment(job, segment)

        self.assertTrue(path.endswith("edited_01.mp4"))
        self.assertEqual(media_task.call_count, 2)
        self.assertEqual(segment["driftRetryCount"], 1)
        self.assertEqual(segment["retryReason"], "visual_drift_blocked")
        self.assertEqual(segment["qcStatus"], "passed")

    def test_non_talking_segment_fails_after_drift_retry_exhausted(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.mp4"
            edited = Path(td) / "edited.mp4"
            make_tone_video(self.client, source, duration=1)
            make_tone_video(self.client, edited, duration=1)
            job = {
                "id": "job-drift-exhausted",
                "identityMode": "standard",
                "outDir": td,
                "sourceVideoPath": str(source),
                "segments": [],
                "productImageUrls": ["https://x/car.png"],
                "modelFaceUrl": "https://x/face.png",
            }
            segment = {"index": 1, "start": 0, "end": 1, "duration": 1, "audioStatus": "pending", "qcStatus": "pending"}
            job["segments"] = [segment]
            qc = {"ok": False, "code": "visual_drift_blocked", "frames": ["a", "b", "c"],
                  "checks": {"media": "passed", "audio": "passed"}, "retryableDrift": True,
                  "visual": {"visualDriftQc": {"severeDrift": True}}}

            with mock.patch.object(self.client, "_extract_replacement_segment", side_effect=lambda _src, _seg, out: shutil.copyfile(source, out)), \
                    mock.patch.object(self.client, "upload_asset_url", return_value=("https://x/source.mp4", {})), \
                    mock.patch.object(self.client, "lk888_media_task", return_value="https://x/edited.mp4"), \
                    mock.patch.object(self.client, "_wf_download", side_effect=lambda _url, path: shutil.copyfile(edited, path)), \
                    mock.patch.object(self.client, "_ensure_segment_audio", return_value=None), \
                    mock.patch.object(self.client, "_run_replacement_segment_qc", side_effect=[qc, qc]), \
                    mock.patch.object(self.client, "_save_replacement_job", return_value=str(Path(td) / "replacement_job.json")):
                with self.assertRaisesRegex(RuntimeError, "visual_drift_retry_exhausted"):
                    self.client._run_hybrid_non_talking_segment(job, segment)

        self.assertEqual(segment["status"], "failed")
        self.assertEqual(segment["qcStatus"], "failed")
        self.assertEqual(segment["blockedReason"], "visual_drift_retry_exhausted")
```

- [ ] **Step 2: Run focused tests and confirm they fail**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_non_talking_segment_retries_once_on_severe_drift \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_non_talking_segment_fails_after_drift_retry_exhausted -v
```

Expected: fail because `_run_hybrid_non_talking_segment()` does not retry drift failures.

- [ ] **Step 3: Implement drift retry helpers**

Add near `_replacement_is_severe_drift_code()`:

```python
def _replacement_can_retry_drift(job, segment, qc=None):
    if not _replacement_drift_auto_retry_enabled(job):
        return False
    segment = segment or {}
    qc = qc or {}
    if not _replacement_is_severe_drift_code(qc.get("code")):
        return False
    try:
        current = int(segment.get("driftRetryCount") or 0)
    except (TypeError, ValueError):
        current = 0
    return current < _replacement_drift_max_retries(job)


def _replacement_mark_drift_retry(job, segment, qc=None):
    segment = segment or {}
    qc = qc or {}
    current = int(segment.get("driftRetryCount") or 0)
    segment["driftRetryCount"] = current + 1
    segment["retryReason"] = qc.get("code") or "visual_drift_blocked"
    segment["status"] = "video_edit"
    segment["qcStatus"] = "retrying"
    segment.setdefault("qcWarnings", []).append({
        "code": qc.get("code") or "visual_drift_blocked",
        "reason": str(((qc.get("visual") or {}).get("reason") or qc.get("reason") or "生成内容偏离原视频主题"))[:180],
        "severity": "blocking",
    })
    _replacement_error_id(
        "video_replace_visual_drift_retry",
        RuntimeError(segment["retryReason"]),
        segment_index=segment.get("index"),
        retry_count=segment["driftRetryCount"],
        source_video=(job or {}).get("sourceVideoPath") or "",
    )


def _replacement_mark_drift_exhausted(segment, qc=None):
    segment = segment or {}
    qc = qc or {}
    segment["status"] = "failed"
    segment["qcStatus"] = "failed"
    segment["blockedReason"] = "visual_drift_retry_exhausted"
    segment["error"] = "visual_drift_retry_exhausted"
    segment.setdefault("qcWarnings", []).append({
        "code": "visual_drift_retry_exhausted",
        "reason": str(((qc.get("visual") or {}).get("reason") or "重试后仍偏离原视频主题"))[:180],
        "severity": "blocking",
    })
```

- [ ] **Step 4: Wrap non-talking remote generation in one-shot retry loop**

In `_run_hybrid_non_talking_segment()`, keep source segment extraction and `upload_asset_url(source_segment, ...)` before retry logic. Put the remote model loop, download, optional FaceFusion, audio muxing, and QC inside `while True`. Replace both existing `if not qc.get("ok"):` blocks in that function with this exact decision block, using `edited_path` in the standard/no-person branch and `final_path` in the high-consistency branch:

```python
            if not qc.get("ok"):
                if _replacement_can_retry_drift(job, segment, qc):
                    _replacement_mark_drift_retry(job, segment, qc)
                    _save_replacement_job(job)
                    _replacement_emit_stage(
                        job,
                        segment,
                        "video_edit",
                        "生成片段 %s：主题跑偏，正在强化原视频锁定后重试" % idx,
                    )
                    continue
                if _replacement_is_severe_drift_code(qc.get("code")):
                    _replacement_mark_drift_exhausted(segment, qc)
                    _save_replacement_job(job)
                    raise RuntimeError("replacement_qc_failed:visual_drift_retry_exhausted")
                raise RuntimeError("replacement_qc_failed:%s" % (qc.get("code") or "unknown"))
```

The successful branches stay as they are: standard/no-person returns `edited_path` after setting `status=done`, and high-consistency returns `final_path` after setting `status=done`. FaceFusion remains inside the loop for `high` mode because the final video being QC'd may include FaceFusion output.

- [ ] **Step 5: Add talking retry around digital-human generation**

In `_run_hybrid_replacement_segment()`, for `segmentType == "talking"`, wrap the keyframe/TTS/digital-human/download/optional-FaceFusion/QC block in the same `while True` retry pattern. On severe drift retry, keep existing `ttsUrl` if available but regenerate digital-human media with stronger source-lock prompt and `driftRetryCount=1`.

- [ ] **Step 6: Run focused tests**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_non_talking_segment_retries_once_on_severe_drift \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_non_talking_segment_fails_after_drift_retry_exhausted -v
.venv/bin/python -m py_compile backend/matrix_native_client.py
```

Expected: focused tests and compile pass.

- [ ] **Step 7: Commit or record no-git status**

If executing in a git worktree:

```bash
git add backend/matrix_native_client.py tests/test_video_replacement_v2.py
git commit -m "feat: retry severe replacement drift once"
```

If no git metadata exists, record that no commit was possible.

---

### Task 6: Status Text, Docs, Changelog, And Full Verification

**Files:**
- Modify: `tests/test_video_replacement_v2.py`
- Modify: `backend/matrix_native_client.py`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/API_REFERENCE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `CHANGELOG.md`
- Modify: `migration.sql`

**Interfaces:**
- Consumes: `referencePreflight`, `visualDriftQc`, `driftRetryCount`, `retryReason`, `blockedReason`
- Produces: localized status/error text for drift preflight, drift retry, and drift exhausted failures

- [ ] **Step 1: Write failing status/documentation contract tests**

Add:

```python
    def test_segment_status_text_includes_drift_retry_and_block_reason(self):
        job = {"identityMode": "standard", "segments": [{"index": 1}]}
        segment = {
            "index": 1,
            "status": "failed",
            "driftRetryCount": 1,
            "retryReason": "visual_drift_blocked",
            "blockedReason": "visual_drift_retry_exhausted",
            "visualDriftQc": {"severeDrift": True, "reason": "汽车销售变成美妆带货"},
        }

        text = self.client._replacement_segment_status_text(job, segment)

        self.assertIn("跑偏重试 1 次", text)
        self.assertIn("已阻断合成", text)
        self.assertIn("汽车销售变成美妆带货", text)

    def test_error_text_localizes_visual_drift_codes(self):
        self.assertIn("偏离原视频主题", self.client._localize_replacement_display_text("visual_drift_blocked"))
        self.assertIn("重试后仍偏离", self.client._localize_replacement_display_text("visual_drift_retry_exhausted"))
        self.assertIn("参考图", self.client._localize_replacement_display_text("reference_mismatch"))
```

- [ ] **Step 2: Run focused tests and confirm they fail**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_segment_status_text_includes_drift_retry_and_block_reason \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_error_text_localizes_visual_drift_codes -v
```

Expected: fail because status and localized text do not yet include drift details.

- [ ] **Step 3: Implement localized text and status additions**

Update the existing display localization mapping near the replacement error helpers with:

```python
    "reference_mismatch": "参考图与原视频主题或产品类别冲突，请更换参考图后重试",
    "visual_drift_blocked": "生成内容偏离原视频主题，已阻断合成",
    "topic_mismatch": "生成内容主题与原视频不一致",
    "role_mismatch": "生成人物角色与原视频不一致",
    "structure_mismatch": "生成镜头结构与原视频不一致",
    "visual_drift_retry_exhausted": "重试后仍偏离原视频主题，片段已失败",
```

Update `_replacement_segment_status_text()` before `display_error`:

```python
    retry_count = int(segment.get("driftRetryCount") or 0)
    if retry_count:
        parts.append("跑偏重试 %d 次" % retry_count)
    blocked_reason = _localize_replacement_display_text(segment.get("blockedReason") or "")
    drift_reason = str((segment.get("visualDriftQc") or {}).get("reason") or "").strip()
    if blocked_reason:
        parts.append("已阻断合成：" + blocked_reason)
    if drift_reason:
        parts.append(drift_reason[:80])
```

- [ ] **Step 4: Update docs and changelog**

Update `CHANGELOG.md` under `2026-07-18`:

```markdown
- 同款替换新增三层跑偏防护：参考图预检、源视频行业/角色/结构锁定提示词、严重主题跑偏 QC；汽车销售视频生成成美妆等无关行业时会自动重试 1 次，仍失败则阻断合成。
- 新增 `VIDEO_REPLACE_DRIFT_GUARD`、`VIDEO_REPLACE_REFERENCE_PREFLIGHT`、`VIDEO_REPLACE_BLOCK_SEVERE_DRIFT`、`VIDEO_REPLACE_DRIFT_AUTO_RETRY`、`VIDEO_REPLACE_DRIFT_MAX_RETRIES` 和 `VIDEO_REPLACE_PREFLIGHT_BLOCK_SCENE` 回滚/灰度开关。
```

Update `migration.sql` to remain no-op but traceable:

```sql
-- Release: 2026-07-18 video replacement drift guard.
-- Database schema/data changes: none.
-- Drift guard state is stored in local replacement_job.json files.
BEGIN;
COMMIT;
```

Update docs:

- `docs/ARCHITECTURE.md`: add the three-layer flow to the same replacement section that currently documents identity modes.
- `docs/API_REFERENCE.md`: document `referencePreflight`, `driftGuardConfig`, `visualDriftQc`, `driftRetryCount`, `retryReason`, `blockedReason`, and new error codes.
- `docs/DEPLOYMENT.md`: add environment-variable table entries and rollback commands.
- `docs/TROUBLESHOOTING.md`: add operator guidance for `reference_mismatch`, `visual_drift_blocked`, and `visual_drift_retry_exhausted`.
- `docs/IMPLEMENTATION.md`: after all code edits, run line-number commands and replace stale `backend/matrix_native_client.py#L...` / `tests/test_video_replacement_v2.py#L...` references.

- [ ] **Step 5: Recalculate implementation line numbers**

Run:

```bash
nl -ba backend/matrix_native_client.py | sed -n '5170,5235p'
nl -ba backend/matrix_native_client.py | sed -n '8770,8915p'
nl -ba backend/matrix_native_client.py | sed -n '9290,9475p'
nl -ba backend/matrix_native_client.py | sed -n '9475,9765p'
nl -ba tests/test_video_replacement_v2.py | sed -n '1,1500p'
```

Use the actual output to update `docs/IMPLEMENTATION.md`. Do not leave approximate line ranges.

- [ ] **Step 6: Run focused and full verification**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_segment_status_text_includes_drift_retry_and_block_reason \
  tests.test_video_replacement_v2.VideoReplacementV2Test.test_error_text_localizes_visual_drift_codes -v
.venv/bin/python -m unittest tests.test_video_replacement_v2 -v
.venv/bin/python -m unittest tests.test_video_replacement -v
.venv/bin/python -m py_compile backend/matrix_native_client.py
```

Expected: all tests pass and compile succeeds.

- [ ] **Step 7: Final no-git or git completion**

If executing in a git worktree:

```bash
git add backend/matrix_native_client.py tests/test_video_replacement_v2.py docs/ARCHITECTURE.md docs/API_REFERENCE.md docs/DEPLOYMENT.md docs/TROUBLESHOOTING.md docs/IMPLEMENTATION.md CHANGELOG.md migration.sql
git commit -m "feat: guard video replacement against topic drift"
```

If no git metadata exists, record the changed files, verification commands, and no-git status in the task report.

---

## Plan Self-Review

- Spec coverage: The plan covers reference preflight, source-lock prompts, severe drift QC, one-shot retry, JSON trace fields, status text, docs, rollback, and tests.
- Placeholder scan: The plan contains no TBD/TODO placeholders. `path#L...` appears only as the required documentation line-reference format.
- Type consistency: Helper names and return keys are consistent across tasks: `referencePreflight`, `driftGuardConfig`, `visualDriftQc`, `driftRetryCount`, `retryReason`, and `blockedReason`.
- Scope check: This is one bounded subsystem inside existing video replacement. It does not add a model provider, database table, local GPU dependency, or unrelated refactor.
