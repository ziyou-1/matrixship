# Workflow Assistant Chat History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the workflow assistant's latest 100 user/assistant conversation rounds per account and restore the visible analysis results and replacement actions when the page is reopened.

**Architecture:** Add small account-scoped JSON persistence helpers beside the existing workflow assistant helpers in `backend/matrix_native_client.py`. `AgentChatPage` keeps its current in-memory rendering path, adds load-on-create/load-on-account-change, and saves after user messages and final assistant replies. Assistant history entries carry `replacementPayloads` so restored messages can recreate the same-style replacement cards without rerunning models.

**Tech Stack:** Python 3, PySide6, JSON files under the existing `data_dir()` account scope, `unittest`, atomic `os.replace`, existing `json_log`/`_workflow_assistant_log` observability.

## Global Constraints

- Keep history account-scoped through `data_dir()`; never mix private-message history with workflow assistant history.
- Persist only role, visible text, timestamps, and replacement payloads; never persist Cookie, Token, Authorization, API keys, or full signed URLs.
- Preserve the current-page display path even when persistence fails.
- Keep the retention limit at the approved latest 100 user/assistant rounds.
- No OpenAPI, database, Docker, `migration.sql`, or central-server changes.
- Before any commit, recalculate `docs/IMPLEMENTATION.md` line references.

---

### Task 1: Add persistence helper contract and regression tests

**Files:**
- Create: `tests/test_workflow_assistant_history.py`
- Modify: `backend/matrix_native_client.py` only after the RED test is verified

**Interfaces:**
- Add `_workflow_assistant_history_path() -> str`.
- Add `_workflow_assistant_history_trim(messages, max_rounds=100) -> list`.
- Add `_load_workflow_assistant_history(path=None) -> list`.
- Add `_save_workflow_assistant_history(messages, path=None) -> bool`.

- [ ] **Step 1: Write the failing tests**

Add tests that extract the helper functions from `backend/matrix_native_client.py` and provide `os`, `json`, `tempfile`, and a stub logger. Cover:

```python
def test_history_is_trimmed_to_latest_100_user_assistant_rounds():
    messages = []
    for index in range(101):
        messages.extend([
            {"role": "user", "content": f"user-{index}"},
            {"role": "assistant", "content": f"assistant-{index}",
             "replacementPayloads": [{"sourceVideoPath": f"video-{index}.mp4"}]},
        ])

    trimmed = helpers["_workflow_assistant_history_trim"](messages)

    self.assertEqual(200, len(trimmed))
    self.assertEqual("user-1", trimmed[0]["content"])
    self.assertEqual("assistant-100", trimmed[-1]["content"])
    self.assertEqual("video-100.mp4",
                     trimmed[-1]["replacementPayloads"][0]["sourceVideoPath"])
```

Also add:

- a round-trip test proving `workflow_assistant_history.json` stores and reloads messages;
- an atomic-save test proving the final file exists and no temporary file remains;
- a malformed JSON test proving load returns `[]` without raising;
- a schema test proving unsupported roles and non-string content are ignored;
- a path test proving `_workflow_assistant_history_path()` is based on the mocked `data_dir()`.

- [ ] **Step 2: Run the focused test file and verify RED**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_workflow_assistant_history -v
```

Expected: FAIL because the four persistence helpers do not exist yet.

- [ ] **Step 3: Implement the minimal persistence helpers**

Implement the helpers near `_workflow_assistant_log`:

```python
def _workflow_assistant_history_path():
    return os.path.join(data_dir(), "workflow_assistant_history.json")


def _workflow_assistant_history_trim(messages, max_rounds=100):
    valid = [...]
    return valid[-max(1, int(max_rounds or 100)) * 2:]


def _load_workflow_assistant_history(path=None):
    ...


def _save_workflow_assistant_history(messages, path=None):
    ...
```

Use a versioned JSON envelope, `tempfile.NamedTemporaryFile(..., delete=False)`, `os.replace`, and existing structured logging. On read/write errors, log only stage, path basename, message count, and `errorId`; return `[]` or `False`.

- [ ] **Step 4: Run the focused test file and verify GREEN**

Run the same `unittest` command. Expected: all history helper tests pass.

- [ ] **Step 5: Run syntax validation**

```powershell
.\.venv-win\Scripts\python.exe -m py_compile backend\matrix_native_client.py tests\test_workflow_assistant_history.py
```

Expected: exit code `0`.

### Task 2: Restore and persist AgentChatPage content

**Files:**
- Modify: `backend/matrix_native_client.py:18175-18320`
- Modify: `tests/test_workflow_assistant_history.py`

**Interfaces:**
- `AgentChatPage._restore_history() -> None`.
- `AgentChatPage._persist_history() -> None`.
- `AgentChatPage._history_account_key() -> str`.
- `AgentChatPage.on_show() -> None`.

- [ ] **Step 1: Write the failing page-behavior tests**

Add source-contract tests for `AgentChatPage` asserting:

```python
self.assertIn("_load_workflow_assistant_history", page_source)
self.assertIn("_save_workflow_assistant_history", page_source)
self.assertIn("replacementPayloads", page_source)
self.assertIn("def on_show", page_source)
self.assertIn("workflow_assistant_history", page_source)
```

Add helper-level restore tests that feed one assistant record containing `replacementPayloads` and verify the restore sequence exposes both the assistant text and payload list to the rendering path.

- [ ] **Step 2: Run the focused page tests and verify RED**

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_workflow_assistant_history -v
```

Expected: the source-contract assertions fail because `AgentChatPage` currently only initializes an empty in-memory history.

- [ ] **Step 3: Implement page integration**

Change `AgentChatPage` so that:

1. `__init__` initializes `self.history`, `self._history_account_key_value`, then calls `_restore_history()` after the message layout exists.
2. `_restore_history()` loads the current account file, appends each message to `self.history`, renders user/assistant bubbles, and calls `_replacement_card()` for each stored payload.
3. `send()` appends the user message with `createdAt`, then calls `_persist_history()`.
4. `_on()` appends the final assistant reply with `createdAt` and `replacementPayloads`, then calls `_persist_history()`.
5. `on_show()` detects a changed `data_dir()` path, clears only the current page widgets/history, and reloads the new account’s history.
6. Status progress bubbles remain transient and are not persisted.
7. Save failures never disable the input or hide the current reply.

- [ ] **Step 4: Run focused tests and verify GREEN**

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_workflow_assistant_history tests.test_workflow_assistant_direct_mode tests.test_workflow_assistant_helpers -v
```

Expected: all focused workflow assistant tests pass.

- [ ] **Step 5: Run a local UI smoke check**

Start the existing client with `start-visible-client.bat`, log in with a test account, send a non-model smoke message or mocked assistant response, navigate to another sidebar page, return to `🤖 工作流助手`, and verify:

- the user message remains visible;
- the assistant response remains visible;
- a stored replacement payload recreates the “按这条改造生成” card;
- switching to another account does not display the first account’s history.

Do not trigger a real LK888 video analysis call during this smoke check.

### Task 3: Update production documentation and final verification

**Files:**
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_workflow_assistant_history.py` if final regression coverage needs tightening

- [ ] **Step 1: Add implementation and troubleshooting notes**

Document the account-scoped history file, 100-round retention rule, transient status-message rule, corruption fallback, and the manual restart requirement. Use exact `backend/matrix_native_client.py#Lx-Ly` references after the final code shape is fixed.

- [ ] **Step 2: Run the complete focused regression set**

```powershell
.\.venv-win\Scripts\python.exe -m unittest `
  tests.test_workflow_assistant_history `
  tests.test_workflow_assistant_direct_mode `
  tests.test_workflow_assistant_helpers `
  tests.test_workflow_assistant_deep_breakdown `
  tests.test_video_transcription -v
```

Expected: zero failures and zero errors.

- [ ] **Step 3: Run final static checks**

```powershell
.\.venv-win\Scripts\python.exe -m py_compile `
  backend\matrix_native_client.py `
  backend\utils\video_transcription.py `
  tests\test_workflow_assistant_history.py
git diff --check
```

Expected: both commands exit `0`.

- [ ] **Step 4: Review rollback scope**

Rollback consists of reverting the workflow assistant persistence changes, focused tests, and documentation, or deleting `workflow_assistant_history.json`. Asset-library videos, text files, and structured analysis sidecars remain untouched.
