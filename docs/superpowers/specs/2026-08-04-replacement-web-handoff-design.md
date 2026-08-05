# Replacement Web Handoff Design

## Goal

Make the local `/replacement` page continue from an existing native same-style video replacement context instead of starting as a disconnected Phase 0 video task.

## Scope

This phase only passes local context from the native client to the local web page. It does not submit LK888 jobs, does not call remote AI Canvas, does not settle billing, and does not publish or upload final video output.

## Recommended Flow

1. The native client already has a `VideoReplacementPage._source` payload from video breakdown.
2. The user clicks `打开网页版替换`.
3. The native client writes a short-lived local handoff JSON under the current agent data directory.
4. The launch URL includes `handoffId` in the hash with the existing local agent token and redacted user context.
5. The web page stores `handoffId` in `sessionStorage`, calls `GET /api/replacement/video/handoff`, and shows that a local breakdown context is attached.
6. `POST /api/replacement/video/start` can receive `handoffId`; when valid, it creates a local video replacement web job bound to the handoff source context.

## Boundaries

- Native client owns writing the handoff file.
- Local executor owns serving and validating the handoff.
- Web UI owns displaying handoff readiness and passing `handoffId` on submit.
- Real video generation remains native-service extraction work for a later phase.

## Safety

- The URL must not expose center tokens, phone numbers, cookies, signed URLs, or local absolute paths.
- API responses must redact local paths and expose only source host/path hashes plus safe metadata.
- Feature remains behind `MATRIX_REPLACEMENT_WEB_ENABLED`.
- Rollback is to disable the feature flag and restore touched files.

## Non-Functional Requirements

- Local-only API latency target: p95 below 300 ms for handoff read and local job creation.
- QPS target: single-user desktop use, 1-3 QPS on local executor.
- GPU/VRAM: no GPU use in this phase.
- Observability: structured logs at page open, handoff read, and video start should include handoff/job ids but no secrets or local paths.
