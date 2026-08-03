# MatrixShip UI Feature Visibility Design

## Scope

Temporarily reduce the production client to the currently supported Douyin workflows while preserving unfinished capabilities for configuration-level recovery.

This change covers:

1. Remove the Xiaohongshu card and metrics contribution from Account Matrix while Xiaohongshu is disabled.
2. Hide the Pending Publish Queue tab inside Material Publish.
3. Keep the Same-style Replacement navigation item visible but disabled, and hide all other entry buttons into that workflow.
4. Hide Digital Human TTS audio upload controls.
5. Filter Xiaohongshu task capabilities from local-browser registration and central-server status while Xiaohongshu is disabled.

The Risk Control Center is not changed in this release.

## Configuration

The existing `MATRIX_XHS_ENABLED` flag continues to control all Xiaohongshu visibility and task capability behavior.

Add three production-default-off flags:

| Environment variable | Default | Restores |
| --- | --- | --- |
| `MATRIX_VIDEO_REPLACEMENT_ENABLED` | `0` | Same-style Replacement navigation and entry buttons |
| `MATRIX_PENDING_PUBLISH_UI_ENABLED` | `0` | Pending Publish Queue tab and navigation alias |
| `MATRIX_DIGITAL_HUMAN_TTS_UPLOAD_ENABLED` | `0` | Digital Human TTS audio upload UI |

Truthy values follow the existing convention: `1`, `true`, `yes`, or `on`.

## Client Behavior

### Account Matrix

When `MATRIX_XHS_ENABLED=0`:

- Build only the Douyin platform card.
- Exclude Xiaohongshu rows from totals and platform metrics.
- Show one available platform when no Douyin account is connected.

When `MATRIX_XHS_ENABLED=1`, the existing Xiaohongshu card and metrics return without a code change.

### Material Publish

When `MATRIX_PENDING_PUBLISH_UI_ENABLED=0`, `PublishWorkspacePage` contains only the Material Library and Publish tab. The Pending Publish Queue page, stored queue data, scheduler behavior, and queue processing code remain intact for rollback and compatibility.

The hidden tab must not retain a navigation alias that can reopen it.

### Same-style Replacement

When `MATRIX_VIDEO_REPLACEMENT_ENABLED=0`:

- Keep the left navigation item visible.
- Render it disabled with the existing disabled-button style.
- Show the tooltip `功能完善中，敬请期待` on hover.
- Reject programmatic navigation to the page.
- Hide the replacement-generation entry in Video Breakdown.
- Hide the replacement jump button in Workflow Assistant reference cards.
- Hide the replacement jump button in Asset Library breakdown dialogs.

The replacement page and generation implementation remain unchanged and become reachable again when the flag is enabled.

### Digital Human TTS Upload

When `MATRIX_DIGITAL_HUMAN_TTS_UPLOAD_ENABLED=0`:

- Hide the TTS audio upload button and unused audio preview frame.
- Remove upload-audio references from the visible instructions.
- Continue using the existing voice selector and automatic TTS path.
- Preserve uploaded-audio processing code for configuration rollback and existing persisted jobs.

## Executor And Central Capability Filtering

When `MATRIX_XHS_ENABLED=0`:

- The local-browser worker must omit all `xhs.*` capabilities during register and poll.
- The central server must filter incoming, stored, and public local-browser capabilities.
- The central server must not include `xhs.*` values in allowed task types.
- Existing persisted clients with historical Xiaohongshu capabilities must be sanitized on read, so a server restart is sufficient and no destructive state migration is required.

When `MATRIX_XHS_ENABLED=1`, the existing Xiaohongshu task paths and capability names are restored.

## Risk Control Status

The current Douyin behavior remains documented as follows:

- Daily comment limits, minimum comment interval, and risk cooldown are enforced per account before a comment is sent.
- Daily publish limit only caps scheduled generation batch size; it is not a hard publish gate.
- Executor concurrency is currently stored and displayed but not enforced.
- Search, download, and direct-message operations do not use the generic risk limits.

No Risk Control behavior changes are included in this implementation.

## Verification

Tests must prove both default-off and explicit-on behavior:

- Account Matrix renders only Douyin by default and restores Xiaohongshu with `MATRIX_XHS_ENABLED=1`.
- Material Publish exposes one tab by default and restores Pending Publish Queue when enabled.
- Same-style Replacement navigation is disabled with the expected tooltip, all secondary entry buttons are hidden, and programmatic navigation is blocked.
- Digital Human hides upload controls and related copy by default and restores them when enabled.
- Local-browser register/poll and central status contain no `xhs.*` capability by default and restore those capabilities when enabled.
- Existing focused UI, XHS-disable, native-publish, OpenAPI-contract, and syntax checks remain green.

Runtime smoke must restart the native client, embedded local executor, and central server with all four flags set to `0`, then verify:

- `9080` and `9081` health endpoints return HTTP 200.
- The local-browser client is online.
- XHS endpoints return HTTP 404 with `platform_disabled`.
- Online capability metadata contains zero `xhs.*` entries.
- The desktop client displays the intended hidden and disabled states.

## Deployment And Rollback

This change does not add API paths, change JSON schemas, modify database tables, or require `migration.sql` changes. OpenAPI remains unchanged.

Configuration rollback:

1. Set the relevant environment variable to `1`.
2. Restart the native client, embedded local executor, and central server.
3. Repeat the corresponding UI and runtime smoke checks.

Code rollback restores the affected client, local-browser worker, central-server, tests, environment examples, deployment documentation, implementation references, troubleshooting notes, and changelog entry.

Pending queue data and unfinished feature implementations are retained, so rollback does not require data recovery.
