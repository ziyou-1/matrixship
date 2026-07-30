-- Release: 2026-07-25 xhs image-note replacement draft workflow.
-- Database schema/data changes: none.
-- This no-op migration is intentionally retained for release traceability.
-- The feature stores local JSON jobs and draft material metadata only.
BEGIN;
COMMIT;
-- Release: 2026-07-28 douyin dm auto-reply MVP.
-- Database schema/data changes: none.
-- The feature uses existing local-browser task records, local JSON conversation history,
-- and browser session state; no SQL migration is required.
-- Release: 2026-07-29 comic dual-frame table and ordered video-model fallback.
-- Database schema/data changes: none. New frame and fallback metadata live in JSON task state.
-- No DDL or DML is required for this release.
-- Release: 2026-07-30 account-center billing dashboard verification and rollback gate.
-- Database schema/data changes: none. This append-only release note is intentionally no-op.
-- No DDL or DML is required for this release.
