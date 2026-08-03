# Task 1: Build the failing Phase 0 provider-contract tests

## Context

This is the first implementation task for the MiniMax official direct integration. It defines the test-visible provider contract before the central server and remote comic generator are touched.

## Global Constraints

- Official direct API only; do not route MiniMax through LK888.
- Text-to-video and image-to-video use `MiniMax-Hailuo-2.3`; first/last-frame uses `MiniMax-Hailuo-02`.
- Use `MINIMAX_CENTER_API_KEY` and `MINIMAX_COMIC_API_KEY`; never hardcode credentials.
- Central and remote concurrency are each limited to 2 active MiniMax tasks.
- Each task has a 900-second timeout and never auto-switches models or resubmits after a provider task ID exists.
- Charge only after successful download and media validation using the official published unit-price table.
- Failed, cancelled, timed-out, safety-rejected, and missing-price tasks are not charged.
- All boundary logs are JSON, redacted, and include error IDs, stages, task IDs, model IDs, and billing refs.
- Do not modify unrelated dirty-worktree files.

## Files

- Create: `tests/test_minimax_direct.py`
- Create: `tests/test_minimax_pricing.py`
- Later implementation files, not in this task: `backend/utils/minimax_direct.py`, `backend/utils/minimax_pricing.py`

## Interfaces Defined by This Task

- `normalize_video_request(payload: dict) -> dict`
- `actual_model_for_mode(mode: str) -> str`
- `MiniMaxDirectClient.submit_video(request: dict) -> str`
- `MiniMaxDirectClient.poll_video(provider_task_id: str) -> dict`
- `MiniMaxDirectClient.retrieve_video(provider_result: dict) -> str`
- `MiniMaxDirectClient.download_video(url: str, destination: Path) -> dict`
- `published_unit_price(model: str, mode: str, duration: int, resolution: str) -> Decimal | None`

## TDD Work

- [ ] Write RED tests for model mapping and request normalization.

```python
from backend.utils.minimax_direct import (
    actual_model_for_mode,
    normalize_video_request,
)


def test_first_last_frame_maps_to_hailuo_02_and_keeps_two_frames():
    request = normalize_video_request(
        {
            "mode": "first_last_frame",
            "prompt": "walk through a station",
            "images": ["https://assets.test/start.png", "https://assets.test/end.png"],
            "duration": 10,
            "resolution": "768P",
        }
    )

    assert actual_model_for_mode(request["mode"]) == "MiniMax-Hailuo-02"
    assert request["images"] == [
        "https://assets.test/start.png",
        "https://assets.test/end.png",
    ]


def test_image_to_video_rejects_local_paths_and_data_urls():
    for value in ("C:\\temp\\start.png", "data:image/png;base64,abc"):
        try:
            normalize_video_request(
                {"mode": "image_to_video", "prompt": "move", "images": [value]}
            )
        except ValueError as exc:
            assert "public" in str(exc).lower()
        else:
            raise AssertionError("unreachable reference was accepted")
```

- [ ] Run RED:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_minimax_direct tests.test_minimax_pricing -v
```

Expected: FAIL because `backend.utils.minimax_direct` does not exist.

- [ ] Add RED lifecycle tests covering:

  - submit returns a provider task ID;
  - two pending polls followed by success;
  - retrieve returns a file URL;
  - download writes bytes to a temporary file;
  - failure status raises a stage-specific error;
  - timeout is reported after the configured deadline.

- [ ] Run the lifecycle RED tests again and verify the failure is caused by the missing adapter, not malformed test setup.

## Scope Boundary

Do not implement production code in this task. Do not modify `backend/central_server.py`, `tools/aicanvas_remote/server_current.py`, OpenAPI files, billing logic, environment files, or deployment files.

## Report

Write the detailed report to:

`docs/superpowers/plans/2026-08-03-minimax-h3-direct-integration-task-1-report.md`

The report must include:

- Status and files changed.
- RED command and relevant failing output.
- Test names added.
- Self-review findings.
- Any concerns about the contract.

Because `.git` is read-only in this workspace, do not claim a commit was created if git rejects the operation. Report the exact git error.
