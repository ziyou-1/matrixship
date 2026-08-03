# MiniMax H3 Direct Integration Task 2 Review

## Spec Compliance

### Task 2 interface coverage

The reviewed source exposes all six interfaces named by Task 2:

- `normalize_video_request(payload)`
- `actual_model_for_mode(mode)`
- `MiniMaxDirectClient.submit_video(request)`
- `MiniMaxDirectClient.poll_video(provider_task_id)`
- `MiniMaxDirectClient.retrieve_video(provider_result)`
- `MiniMaxDirectClient.download_video(url, destination)`
- `published_unit_price(model, mode, duration, resolution)`

The tests cover model mapping, normalization, a fake submit/poll/retrieve/download flow, one failed status, one timeout, and one unknown price. The focused command passed 9/9 tests:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_minimax_direct tests.test_minimax_pricing -v
```

### Model and mode mapping

Relative to the repository Task 2 plan, the mapping is centralized and internally consistent:

- `text_to_video` -> `MiniMax-Hailuo-2.3`
- `image_to_video` -> `MiniMax-Hailuo-2.3`
- `first_last_frame` -> `MiniMax-Hailuo-02`

However, this is not compliant with the current official MiniMax H3 API contract. The current official video-generation guide identifies the model as `MiniMax-H3`, uses `/v2/video_generation`, sends a multimodal `content[]` payload, and queries `/v2/query/video_generation/{task_id}`. Successful output is returned as `task.content.url`, not through the legacy `file_id` plus `/v1/files/retrieve` flow. The current guide also documents 4-15 second integer durations and 768P/2K output, while this implementation hard-codes durations `{6, 10}` and resolutions `{"512P", "768P", "1080P"}`. This is a release-blocking contract mismatch.

### URL and credential handling

Positive:

- API keys are passed through the `Authorization` header.
- The fake-provider test confirms the header is used.
- `download_video()` deliberately sends no Authorization header to the returned media URL, which is appropriate for a provider-signed HTTPS download URL.
- No reviewed module logs URLs, headers, response bodies, or API keys.

Gaps:

- `_https_url()` checks only the URL scheme. It accepts malformed HTTPS values without a host, and does not enforce a public/non-local hostname despite the error text saying “public HTTPS URL”.
- `MiniMaxDirectClient` does not reject an HTTP `base_url`.
- An empty API key is accepted and produces `Authorization: Bearer `.

### Timeout, status, and exception behavior

Positive:

- Pending, success, failed, cancelled/canceled, and malformed statuses have explicit branches.
- A configured polling deadline exists and defaults to 900 seconds.
- Provider task IDs are retained during polling.

Gaps:

- `poll_interval_sec` is stored but never used. The client neither sleeps nor otherwise enforces the configured interval.
- The timeout clock starts on the first `poll_video()` call, not at submission. Time spent between submit and the first poll is therefore outside the 900-second lifecycle deadline.
- Network errors, HTTP errors, and request timeouts escape as raw `urllib` exceptions rather than stage-specific `MiniMaxDirectError` instances with provider/task context.
- `_response_json()` always labels malformed JSON as a `retrieve` error, even when called from `submit_video()` or `poll_video()`.
- Failure details such as safety rejection are reduced to a generic `poll: provider task failed` message instead of preserving a sanitized provider code/message.

### Download and URL logging

The implementation does not write the private media URL to logs because it contains no logging code. It also requires HTTPS before downloading and returns path, byte count, and content type metadata.

The download path still lacks status/content validation: it does not call an equivalent of `raise_for_status()`, check an HTTP status field, reject an HTML/JSON error body, or require a non-empty body. A provider error response could therefore be written as an `.mp4` and deferred to later media validation. That may be acceptable only if the caller treats this method as raw transport and immediately performs mandatory media validation; the method itself does not make that boundary explicit.

### Price table

The table is keyed by model, mode, duration, and resolution, and returns `Decimal` or `None`. A version constant exists.

It does not satisfy the production billing requirement:

- `_PUBLISHED_PRICES_USD` asserts USD without a documented official source.
- `0.28`, `0.56`, `0.49`, `0.10`, and `0.15` are hard-coded without an effective date, source identifier, region, tax treatment, or unit definition.
- The tests merely ratify the same unverified values; they do not prove publication provenance.
- The current official MiniMax video resource-package page uses “video points” rather than USD and states that the package does not support MiniMax H3. It lists point deductions such as 1 point for 768P/6s and 2 points for 768P/10s for Hailuo-02/Hailuo-2.3, but that is not evidence that `Decimal("0.28")` USD is a valid H3 settlement amount.

The `PRICE_TABLE_VERSION = "minimax-paygo-2026-08"` value is therefore not auditable as written.

## Strengths

- Clear separation between normalization, model mapping, transport, polling, retrieval, download, and pricing.
- No hard-coded secret values in the reviewed production modules.
- Authorization is not forwarded to the media download URL.
- HTTPS checks exist for image references and provider media URLs.
- First/last-frame requires exactly two image references.
- The fake provider is dependency-injected, deterministic, and network-free.
- The focused tests are readable and currently pass.
- Unknown price combinations return `None`, which is safer than silently estimating an amount.

## Issues

### Critical

1. **Official H3 API contract is not implemented.** `backend/utils/minimax_direct.py:9-15, 155-179, 216-241` targets legacy Hailuo model IDs and `/v1/*` endpoints, while the current official H3 guide specifies `MiniMax-H3`, `/v2/video_generation`, `content[]`, `/v2/query/video_generation/{task_id}`, and `task.content.url`. The current implementation would not submit the Task 2 integration described as MiniMax H3 direct integration.

2. **Pricing is not source-backed and is unsafe for settlement.** `backend/utils/minimax_pricing.py:4-19, 28` labels the table USD and encodes `0.28` without official source, currency/region semantics, or price-table evidence. The current official page describes video-point deductions and explicitly says that the displayed video package does not support MiniMax H3. This must be reconciled before any billing or central-server work.

### Important

1. **Stage errors are incorrect for malformed responses.** `backend/utils/minimax_direct.py:39-46` hard-codes the message prefix `retrieve:` even when submit or poll JSON parsing fails.

2. **Transport failures lack the required stage/context classification.** `submit_video`, `poll_video`, `retrieve_video`, and `download_video` do not wrap `urllib` HTTP, timeout, DNS, or connection exceptions with stage, provider task ID, model, and sanitized error context.

3. **The configured poll interval is dead configuration.** `backend/utils/minimax_direct.py:125-132` stores `poll_interval_sec`, but `poll_video()` never uses it. This makes the advertised polling control ineffective.

4. **The timeout starts too late.** `backend/utils/minimax_direct.py:181-189` initializes the deadline on the first poll, so the 900-second limit does not cover time from provider submission to first poll.

5. **Download transport accepts error bodies.** `backend/utils/minimax_direct.py:243-261` writes any returned bytes without checking status, content type, or non-empty content. The later media-validation boundary must be explicit and mandatory.

6. **“Public HTTPS” validation is incomplete.** `backend/utils/minimax_direct.py:59-62` validates only `scheme == "https"`; it does not require a hostname or reject local/private targets.

7. **Tests do not cover the important failure branches.** `tests/test_minimax_direct.py` has no cancelled-status test, malformed JSON test, HTTP/network exception test, non-HTTPS provider-file test, data-URL provider-file test, download error-body test, or assertion that poll interval and timeout lifecycle semantics are enforced.

### Minor

1. `api_key` is not validated as non-empty at client construction.
2. `_urllib_request()` shadows the imported `json` module parameter and uses `__import__("json")`; this is functional but unnecessarily opaque.
3. Pricing tests assert values but not currency, unit, source, effective date, or table version.
4. The tests use `https://api.test` and `https://cdn.test`, so they prove the fake transport contract but not official endpoint compatibility.

## Assessment

**Not ready to proceed to Task 3.**

The focused tests pass, but they validate an internally consistent legacy-Hailuo adapter rather than the current official MiniMax H3 contract. The API/model mismatch is Critical, and the unsupported `0.28` USD pricing assertion is independently Critical because it could cause incorrect production charges. Reconcile the official H3 API version/model/payload and obtain a source-backed currency/unit/versioned price table before central-server integration or billing work.

No reviewed source or test file was modified by this review. Only this report was created.
