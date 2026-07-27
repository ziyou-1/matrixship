# 小红书获客采集数据过滤 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在小红书后端采集阶段清洗评论元信息，过滤无主页链接、空用户名和用户名等于评论的记录，按主页保留最优线索，并为每条淘汰数据生成脱敏结构化日志。

**Architecture:** 保留现有 `/api/xhs/comments` 和 `/api/finder/discover` 契约，在 `backend/platform_adapters.py` 内增加可独立测试的解析、清洗、校验、指纹和主页级归并函数。Playwright 只返回明确评论行的原始换行文本和主页链接，Python 统一执行严格过滤；单笔记和跨笔记复用同一管线。

**Tech Stack:** Python 3、Playwright sync API、Loguru、`utils.structured_log.json_log`、标准库 `hashlib/re/urllib.parse`、Python `unittest`。

## Global Constraints

- 只修改小红书读取链路，不改变抖音获客行为。
- 不新增外部网络请求、私有小红书 API、第三方依赖、数据库表或迁移。
- 无有效小红书主页链接、用户名为空、用户名等于清洗后评论时过滤。
- `.` 和纯 emoji 用户名只要主页链接有效就保留。
- 只清除评论末尾的时间、地区、作者、点赞和回复元信息，不全局删除正文自然用词。
- 相同主页保留意向等级最高记录；同等级保留点赞数更高记录；仍相同时保留第一条。
- 每条过滤和去重淘汰记录必须写 JSON 日志，不得包含原始用户名、评论、完整主页链接或查询 token。
- `XHS_STRICT_LEAD_FILTER_ENABLED` 默认开启，可用于紧急关闭严格校验和主页级去重。
- 单次最多 300 条结果；纯过滤 300 条目标耗时低于 5 ms，测试环境硬上限 50 ms；额外内存低于 5 MB；GPU 显存为 0。
- API 请求和响应字段不变，因此不修改 OpenAPI、`API_REFERENCE.md` 或 `migration.sql`。
- `docs/IMPLEMENTATION.md` 和 `docs/TROUBLESHOOTING.md` 已有用户未提交修改，实施时必须保留，不得用 HEAD 内容覆盖。
- 任何实现提交之前，先完成测试、最终行号重算和全部文档同步。由于该原子行号要求，本计划不做中间代码提交。

---

## File Structure

- Modify `backend/platform_adapters.py`: 评论文本解析、尾部清洗、主页规范化、校验、脱敏日志、主页级归并、DOM 候选收紧和跨笔记去重。
- Create `tests/test_xhs_lead_filtering.py`: 过滤规则、清洗边界、日志脱敏、环境开关、DOM 源码契约和跨笔记回归测试。
- Modify `backend/.env.example`: 新增非敏感严格过滤开关示例。
- Modify `docs/DEPLOYMENT.md`: 环境变量和紧急回滚方式。
- Modify `docs/IMPLEMENTATION.md`: 最终代码和测试行号索引。
- Modify `docs/TROUBLESHOOTING.md`: Phase 0 失败、原因码、日志排查和回滚说明。
- Modify `CHANGELOG.md`: 用户可见修复与运维影响。
- Create ignored rollback archive under `backups/xhs-lead-filtering-20260727/`: 修改前文件副本和 SHA-256 清单。

---

### Task 0: Rollback Baseline And Phase 0 Evidence

**Files:**
- Archive: `backups/xhs-lead-filtering-20260727/`
- Modify: `docs/TROUBLESHOOTING.md`

**Interfaces:**
- Produces: 可校验的修改前文件归档和 `manifest.sha256`。
- Produces: Phase 0 复现记录，供最终排障文档和验收使用。
- Consumed by: 最终回滚验证。

- [ ] **Step 1: Confirm the exact dirty state before editing**

Run:

```powershell
git status --short -- backend/platform_adapters.py backend/.env.example CHANGELOG.md docs/DEPLOYMENT.md docs/IMPLEMENTATION.md docs/TROUBLESHOOTING.md tests/test_xhs_lead_filtering.py
git diff -- docs/IMPLEMENTATION.md docs/TROUBLESHOOTING.md
```

Expected: `backend/platform_adapters.py`, `backend/.env.example`, `CHANGELOG.md`, and `docs/DEPLOYMENT.md` are untracked; `docs/IMPLEMENTATION.md` and `docs/TROUBLESHOOTING.md` contain pre-existing unstaged changes. Save the command output in the task notes and do not revert it.

- [ ] **Step 2: Create a recoverable pre-edit archive**

Run these PowerShell commands from the repository root:

```powershell
$archiveRoot = Join-Path (Get-Location) 'backups\xhs-lead-filtering-20260727'
$sourceRoot = Join-Path $archiveRoot 'pre-edit'
New-Item -ItemType Directory -Force -Path (Join-Path $sourceRoot 'backend') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $sourceRoot 'docs') | Out-Null
Copy-Item -LiteralPath 'backend\platform_adapters.py' -Destination (Join-Path $sourceRoot 'backend\platform_adapters.py')
Copy-Item -LiteralPath 'backend\.env.example' -Destination (Join-Path $sourceRoot 'backend\.env.example')
Copy-Item -LiteralPath 'CHANGELOG.md' -Destination (Join-Path $sourceRoot 'CHANGELOG.md')
Copy-Item -LiteralPath 'docs\DEPLOYMENT.md' -Destination (Join-Path $sourceRoot 'docs\DEPLOYMENT.md')
Copy-Item -LiteralPath 'docs\IMPLEMENTATION.md' -Destination (Join-Path $sourceRoot 'docs\IMPLEMENTATION.md')
Copy-Item -LiteralPath 'docs\TROUBLESHOOTING.md' -Destination (Join-Path $sourceRoot 'docs\TROUBLESHOOTING.md')
Get-ChildItem -LiteralPath $sourceRoot -File -Recurse | Sort-Object FullName | Get-FileHash -Algorithm SHA256 | ForEach-Object { '{0}  {1}' -f $_.Hash.ToLowerInvariant(), $_.Path.Substring($sourceRoot.Length + 1) } | Set-Content -Encoding ascii -LiteralPath (Join-Path $archiveRoot 'manifest.sha256')
```

Expected: six source/document files exist below `pre-edit`, and `manifest.sha256` contains six lowercase SHA-256 entries. `backups/` remains ignored and is not staged.

- [ ] **Step 3: Re-run the current fake-data smoke**

Run:

```powershell
.venv-win\Scripts\python.exe -c "import json,sys; sys.stdout.reconfigure(encoding='utf-8'); from backend.platform_adapters import _xhs_normalize_comment; rows=[{'user':'.','text':'价格','profile':''},{'user':'🌙','text':'价格 07-17 黑龙江 赞 回复','profile':'https://www.xiaohongshu.com/user/profile/abc'},{'user':'在那，价格多少','text':'在那，价格多少','profile':''}]; print(json.dumps([_xhs_normalize_comment(row,note_id='note-smoke',idx=i) for i,row in enumerate(rows)],ensure_ascii=False))"
```

Expected: current code incorrectly returns all three rows; the first has no profile, the second retains `赞 回复`, and the third has identical user/comment fields.

- [ ] **Step 4: Record the baseline failure before production edits**

Append this exact section to `docs/TROUBLESHOOTING.md` with `apply_patch`, preserving every existing line:

```markdown
## 2026-07-27 小红书获客采集假数据基线

- 现象：获客中心出现主页链接为 `-`、用户名为空或等于评论、同一主页重复，以及评论末尾带时间、地区、作者、`赞N`、`回复`的记录。
- 根因：`backend/platform_adapters.py` 把评论容器内普通 `div` 也作为候选，并在压平换行后猜测用户名和正文；归一化阶段未校验主页，跨笔记按“用户名 + 评论”去重。
- Phase 0：假数据调用 `_xhs_normalize_comment()` 后三类无效记录全部被接受，证明现有代码缺少过滤行为。Windows 默认 GBK 标准输出无法打印 emoji，测试命令必须显式把 stdout 配置为 UTF-8；这不是业务模块导入失败。
- 预期修复：在采集层收紧评论节点，清洗尾部元信息，按主页校验和去重，并为每条淘汰记录写脱敏 JSON 日志。
- 回滚基线：修改前文件位于 `backups/xhs-lead-filtering-20260727/pre-edit/`，使用同目录 `manifest.sha256` 校验后恢复。
```

Expected: only the new section is added; all pre-existing user changes remain byte-for-byte present.

- [ ] **Step 5: Verify the archive can be checked without restoring it**

Run:

```powershell
$archiveRoot = Join-Path (Get-Location) 'backups\xhs-lead-filtering-20260727'
$sourceRoot = Join-Path $archiveRoot 'pre-edit'
$actual = Get-ChildItem -LiteralPath $sourceRoot -File -Recurse | Sort-Object FullName | Get-FileHash -Algorithm SHA256 | ForEach-Object { '{0}  {1}' -f $_.Hash.ToLowerInvariant(), $_.Path.Substring($sourceRoot.Length + 1) }
$expected = Get-Content -Encoding ascii -LiteralPath (Join-Path $archiveRoot 'manifest.sha256')
Compare-Object -ReferenceObject $expected -DifferenceObject $actual
```

Expected: no output. Do not restore files during normal implementation.

---

### Task 1: Comment Parsing, Cleaning, And Validation

**Files:**
- Create: `tests/test_xhs_lead_filtering.py`
- Modify: `backend/platform_adapters.py:10-15`
- Modify: `backend/platform_adapters.py:545-575`

**Interfaces:**
- Produces: `xhs_strict_lead_filter_enabled(env: dict | None = None) -> bool`
- Produces: `_xhs_clean_comment_text(value: object) -> str`
- Produces: `_xhs_canonical_profile_url(value: object) -> str`
- Produces: `_xhs_comment_fields(raw: dict) -> tuple[str, str]`
- Produces: `_xhs_prepare_comment(raw: dict, note_id: str = "", source: dict | None = None, idx: int = 0, strict: bool | None = None) -> tuple[dict, str]`
- Consumed by: Task 2 filtering pipeline and Task 3 browser integration.

- [ ] **Step 1: Write focused failing tests**

Create `tests/test_xhs_lead_filtering.py` with this initial content:

```python
import unittest

from backend import platform_adapters as xhs


class XhsLeadParsingTests(unittest.TestCase):
    def test_strict_filter_flag_defaults_on_and_can_disable(self):
        self.assertTrue(xhs.xhs_strict_lead_filter_enabled({}))
        self.assertFalse(xhs.xhs_strict_lead_filter_enabled({"XHS_STRICT_LEAD_FILTER_ENABLED": "0"}))
        self.assertFalse(xhs.xhs_strict_lead_filter_enabled({"XHS_STRICT_LEAD_FILTER_ENABLED": "false"}))
        self.assertTrue(xhs.xhs_strict_lead_filter_enabled({"XHS_STRICT_LEAD_FILTER_ENABLED": "1"}))

    def test_comment_cleaner_removes_only_trailing_xhs_metadata(self):
        self.assertEqual(
            xhs._xhs_clean_comment_text("价格多少 07-17 黑龙江 作者 · 赞 12 回复"),
            "价格多少",
        )
        self.assertEqual(xhs._xhs_clean_comment_text("这个回答值得赞"), "这个回答值得赞")
        self.assertEqual(xhs._xhs_clean_comment_text("求回复一下"), "求回复一下")

    def test_raw_dom_lines_use_username_and_first_comment_only(self):
        user, text = xhs._xhs_comment_fields(
            {
                "rawText": "正常用户\n价格多少\n07-17 黑龙江 赞 回复\n回复用户\n我也想问",
            }
        )
        self.assertEqual(user, "正常用户")
        self.assertEqual(text, "价格多少")

    def test_profile_url_is_canonical_and_drops_query_values(self):
        self.assertEqual(
            xhs._xhs_canonical_profile_url(
                "https://www.xiaohongshu.com/user/profile/abc123?xsec_token=secret#reply"
            ),
            "https://www.xiaohongshu.com/user/profile/abc123",
        )
        self.assertEqual(xhs._xhs_canonical_profile_url("https://evil.example/user/profile/abc123"), "")

    def test_prepare_rejects_missing_or_invalid_profile(self):
        item, reason = xhs._xhs_prepare_comment({"user": "小王", "text": "价格", "profile": ""}, strict=True)
        self.assertEqual(reason, "missing_profile_url")
        self.assertEqual(item["user"], "小王")

        _item, reason = xhs._xhs_prepare_comment(
            {"user": "小王", "text": "价格", "profile": "https://evil.example/user/profile/abc"},
            strict=True,
        )
        self.assertEqual(reason, "invalid_profile_url")

    def test_prepare_rejects_empty_user_and_user_equal_to_comment(self):
        profile = "https://www.xiaohongshu.com/user/profile/abc"
        _item, reason = xhs._xhs_prepare_comment({"user": "", "text": "价格", "profile": profile}, strict=True)
        self.assertEqual(reason, "empty_user")

        _item, reason = xhs._xhs_prepare_comment(
            {"user": "在那，价格多少", "text": "在那，价格多少", "profile": profile},
            strict=True,
        )
        self.assertEqual(reason, "user_equals_comment")

    def test_dot_and_emoji_usernames_are_valid_with_profile(self):
        for index, user in enumerate((".", "🌙"), start=1):
            item, reason = xhs._xhs_prepare_comment(
                {
                    "user": user,
                    "text": "价格多少",
                    "profile": "https://www.xiaohongshu.com/user/profile/user%s" % index,
                },
                strict=True,
            )
            self.assertEqual(reason, "")
            self.assertEqual(item["user"], user)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify the RED state**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_xhs_lead_filtering.XhsLeadParsingTests -v
```

Expected: tests fail with missing helper attributes; existing behavior also defaults an empty user to `小红书用户` and retains metadata.

- [ ] **Step 3: Add imports, constants, and pure helpers**

At the top of `backend/platform_adapters.py`, add `hashlib`, Loguru, and a package-compatible structured logger import:

```python
import hashlib

from loguru import logger

try:
    from utils.structured_log import json_log
except ModuleNotFoundError:
    from backend.utils.structured_log import json_log
```

Add these helpers immediately before `_xhs_normalize_comment()`:

```python
XHS_STRICT_LEAD_FILTER_ENV = "XHS_STRICT_LEAD_FILTER_ENABLED"
_XHS_COMMENT_ACTION_TAIL_RE = re.compile(
    r"(?:\s+(?:赞(?:\s*\d+)?|回复|作者(?:\s*[·•.]?\s*)?))+\s*$"
)
_XHS_COMMENT_TIME_TAIL_RE = re.compile(
    r"\s+(?:作者\s*[·•.]?\s*)?"
    r"(?:刚刚|\d+\s*(?:秒|分钟|小时|天|周|月|年)前|(?:\d{4}-)?\d{1,2}-\d{1,2})"
    r"(?:\s*[\u4e00-\u9fff]{1,8})?\s*$"
)


def xhs_strict_lead_filter_enabled(env=None):
    env = os.environ if env is None else env
    return str(env.get(XHS_STRICT_LEAD_FILTER_ENV, "1")).strip().lower() not in (
        "0", "false", "no", "off"
    )


def _xhs_clean_comment_text(value):
    text = compact_text(value, 0)
    while text:
        cleaned = _XHS_COMMENT_ACTION_TAIL_RE.sub("", text).strip()
        cleaned = _XHS_COMMENT_TIME_TAIL_RE.sub("", cleaned).strip()
        if cleaned == text:
            break
        text = cleaned
    return text


def _xhs_canonical_profile_url(value):
    raw = str(value or "").strip()
    if not raw or raw == "-":
        return ""
    try:
        parsed = urlparse(raw)
    except Exception:
        return ""
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme.lower() not in ("http", "https"):
        return ""
    if host != "xiaohongshu.com" and not host.endswith(".xiaohongshu.com"):
        return ""
    match = re.fullmatch(r"/user/profile/([^/?#]+)/?", parsed.path or "")
    if not match:
        return ""
    user_id = match.group(1).strip()
    if not user_id:
        return ""
    return "https://www.xiaohongshu.com/user/profile/" + quote(user_id, safe="-._~")


def _xhs_comment_fields(raw):
    raw = raw or {}
    user = compact_text(raw.get("user") or raw.get("u") or "", 120)
    text = compact_text(raw.get("text") or raw.get("c") or "", 500)
    raw_text = str(raw.get("rawText") or raw.get("raw_text") or "")
    lines = [compact_text(line, 0) for line in raw_text.splitlines()]
    lines = [line for line in lines if line]
    if not user and lines:
        user = compact_text(lines[0], 120)
    if not text and len(lines) > 1:
        text = compact_text(lines[1], 500)
    return user, _xhs_clean_comment_text(text)
```

- [ ] **Step 4: Replace normalization and add validation**

Replace `_xhs_normalize_comment()` with this behavior, preserving the current response fields:

```python
def _xhs_normalize_comment(raw, note_id="", source=None, idx=0):
    raw = raw or {}
    source = source or {}
    user, text = _xhs_comment_fields(raw)
    profile = str(
        raw.get("profile")
        or raw.get("profileUrl")
        or raw.get("userUrl")
        or raw.get("user_url")
        or ""
    ).strip()
    effective_note_id = str(note_id or raw.get("noteId") or raw.get("awemeId") or "")
    cid = str(raw.get("id") or raw.get("commentId") or ("xhsc_" + str(idx) + "_" + uuid.uuid4().hex[:8]))
    return {
        "id": cid,
        "commentId": cid,
        "text": text,
        "c": text,
        "user": user,
        "u": user,
        "uniqueId": profile,
        "profileUrl": profile,
        "userUrl": profile,
        "user_url": profile,
        "fans": raw.get("fans") or "",
        "intent": raw.get("intent") or classify_intent(text),
        "diggCount": int(raw.get("diggCount") or 0),
        "replyCount": int(raw.get("replyCount") or 0),
        "ip": raw.get("ip") or "",
        "createTime": raw.get("createTime") or 0,
        "platform": "xhs",
        "noteId": effective_note_id,
        "awemeId": effective_note_id,
        "sourceAwemeId": str(raw.get("sourceAwemeId") or effective_note_id),
        "sourceVideoUrl": raw.get("sourceVideoUrl") or source.get("work_url") or source.get("note_url") or _xhs_note_url(effective_note_id),
        "sourceVideoTitle": raw.get("sourceVideoTitle") or source.get("title") or "",
        "sourceAuthor": raw.get("sourceAuthor") or source.get("nickname") or source.get("author") or "",
    }


def _xhs_prepare_comment(raw, note_id="", source=None, idx=0, strict=None):
    item = _xhs_normalize_comment(raw, note_id=note_id, source=source, idx=idx)
    strict = xhs_strict_lead_filter_enabled() if strict is None else bool(strict)
    if not strict:
        if not item.get("user"):
            item["user"] = item["u"] = "小红书用户"
        return item, ""

    raw_profile = str(item.get("profileUrl") or "").strip()
    if not raw_profile or raw_profile == "-":
        return item, "missing_profile_url"
    profile = _xhs_canonical_profile_url(raw_profile)
    if not profile:
        return item, "invalid_profile_url"
    item["uniqueId"] = profile
    item["profileUrl"] = profile
    item["userUrl"] = profile
    item["user_url"] = profile
    user = compact_text(item.get("user"), 120)
    text = compact_text(item.get("text"), 500)
    item["user"] = item["u"] = user
    item["text"] = item["c"] = text
    if not user:
        return item, "empty_user"
    if user.casefold() == text.casefold():
        return item, "user_equals_comment"
    return item, ""
```

- [ ] **Step 5: Run the parsing tests and compile check**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_xhs_lead_filtering.XhsLeadParsingTests -v
.venv-win\Scripts\python.exe -m py_compile backend\platform_adapters.py tests\test_xhs_lead_filtering.py
```

Expected: all parsing tests pass and compilation exits with code 0.

- [ ] **Step 6: Record a checkpoint without committing**

Run:

```powershell
git diff --check -- backend/platform_adapters.py tests/test_xhs_lead_filtering.py
git status --short -- backend/platform_adapters.py tests/test_xhs_lead_filtering.py
```

Expected: no whitespace errors. Do not commit yet because final `IMPLEMENTATION.md` line numbers are not stable.

---

### Task 2: Strict Filtering, Deduplication, And Redacted Logs

**Files:**
- Modify: `tests/test_xhs_lead_filtering.py`
- Modify: `backend/platform_adapters.py`

**Interfaces:**
- Consumes: Task 1 `_xhs_prepare_comment()` and canonical profile URLs.
- Produces: `_xhs_filter_comment_candidates(raw_items: list[dict], note_id: str = "", source: dict | None = None, log=None, strict: bool | None = None) -> list[dict]`
- Produces events: `xhs_collected_record_filtered`, `xhs_collected_record_deduplicated`, `xhs_collected_record_parse_failed`, `xhs_collection_filter_summary`.
- Consumed by: Task 3 single-note and cross-note collection flows.

- [ ] **Step 1: Add failing pipeline and log tests**

Insert these imports and helpers at the top of `tests/test_xhs_lead_filtering.py`:

```python
import json
import re
import time


class FakeLogger:
    def __init__(self):
        self.rows = []

    def warning(self, value):
        self.rows.append(("warning", value))

    def info(self, value):
        self.rows.append(("info", value))

    def error(self, value):
        self.rows.append(("error", value))
```

Add this class before the module main guard:

```python
class XhsLeadFilteringTests(unittest.TestCase):
    def test_fake_data_smoke_filters_invalid_rows_and_keeps_dot_and_emoji(self):
        logger = FakeLogger()
        rows = [
            {"user": "无链接", "text": "价格", "profile": ""},
            {"user": "", "text": "价格", "profile": "https://www.xiaohongshu.com/user/profile/empty"},
            {"user": "在那，价格多少", "text": "在那，价格多少", "profile": "https://www.xiaohongshu.com/user/profile/equal"},
            {"user": ".", "text": "价格多少 07-17 黑龙江 赞 回复", "profile": "https://www.xiaohongshu.com/user/profile/dot"},
            {"user": "🌙", "text": "想了解", "profile": "https://www.xiaohongshu.com/user/profile/moon"},
        ]
        result = xhs._xhs_filter_comment_candidates(rows, note_id="note-smoke", log=logger, strict=True)

        self.assertEqual([item["user"] for item in result], [".", "🌙"])
        self.assertEqual(result[0]["text"], "价格多少")
        payloads = [json.loads(raw) for _level, raw in logger.rows]
        self.assertEqual(
            {payload["reason"] for payload in payloads if payload["event"] == "xhs_collected_record_filtered"},
            {"missing_profile_url", "empty_user", "user_equals_comment"},
        )

    def test_same_profile_keeps_best_intent_then_highest_likes(self):
        profile = "https://www.xiaohongshu.com/user/profile/repeat"
        rows = [
            {"user": "用户", "text": "普通内容", "profile": profile, "intent": "普通", "diggCount": 100},
            {"user": "用户", "text": "想了解", "profile": profile, "intent": "咨询", "diggCount": 2},
            {"user": "用户", "text": "价格多少", "profile": profile, "intent": "高意向", "diggCount": 1},
            {"user": "用户", "text": "怎么买", "profile": profile, "intent": "高意向", "diggCount": 8},
        ]
        result = xhs._xhs_filter_comment_candidates(rows, note_id="note-rank", log=FakeLogger(), strict=True)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "怎么买")
        self.assertEqual(result[0]["diggCount"], 8)

    def test_same_name_with_different_profiles_is_not_deduplicated(self):
        rows = [
            {"user": "同名", "text": "价格", "profile": "https://www.xiaohongshu.com/user/profile/a"},
            {"user": "同名", "text": "怎么买", "profile": "https://www.xiaohongshu.com/user/profile/b"},
        ]
        result = xhs._xhs_filter_comment_candidates(rows, log=FakeLogger(), strict=True)
        self.assertEqual(len(result), 2)

    def test_filtered_logs_are_json_and_do_not_contain_raw_pii_or_token(self):
        logger = FakeLogger()
        user = "sensitive-user"
        comment = "sensitive-comment-price"
        url = "https://evil.example/user/profile/private-id?xsec_token=secret-value"
        xhs._xhs_filter_comment_candidates(
            [{"user": user, "text": comment, "profile": url}],
            note_id="note-log",
            log=logger,
            strict=True,
        )
        joined = "\n".join(raw for _level, raw in logger.rows)
        self.assertNotIn(user, joined)
        self.assertNotIn(comment, joined)
        self.assertNotIn(url, joined)
        self.assertNotIn("secret-value", joined)
        payload = next(json.loads(raw) for _level, raw in logger.rows if json.loads(raw)["event"] == "xhs_collected_record_filtered")
        self.assertEqual(payload["reason"], "invalid_profile_url")
        self.assertRegex(payload["recordFingerprint"], r"^[0-9a-f]{16}$")

    def test_malformed_candidate_logs_redacted_stack_and_does_not_abort_batch(self):
        logger = FakeLogger()
        result = xhs._xhs_filter_comment_candidates(
            [
                {
                    "user": "sensitive-user",
                    "text": "sensitive-comment",
                    "profile": "https://www.xiaohongshu.com/user/profile/private-id?token=secret-value",
                    "diggCount": "not-a-number",
                },
                {
                    "user": "正常用户",
                    "text": "价格多少",
                    "profile": "https://www.xiaohongshu.com/user/profile/valid-id",
                },
            ],
            note_id="note-parse",
            log=logger,
            strict=True,
        )
        self.assertEqual([item["user"] for item in result], ["正常用户"])
        joined = "\n".join(raw for _level, raw in logger.rows)
        self.assertNotIn("sensitive-user", joined)
        self.assertNotIn("sensitive-comment", joined)
        self.assertNotIn("secret-value", joined)
        payload = next(
            json.loads(raw)
            for _level, raw in logger.rows
            if json.loads(raw)["event"] == "xhs_collected_record_parse_failed"
        )
        self.assertEqual(payload["reason"], "parse_failed")
        self.assertEqual(payload["exceptionType"], "ValueError")
        self.assertIn("stack", payload)

    def test_strict_filter_can_be_disabled_for_emergency_rollback(self):
        result = xhs._xhs_filter_comment_candidates(
            [{"user": "", "text": "价格", "profile": ""}],
            log=FakeLogger(),
            strict=False,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["user"], "小红书用户")

    def test_three_hundred_candidate_filter_stays_under_test_budget(self):
        rows = [
            {
                "user": "用户%s" % index,
                "text": "价格多少",
                "profile": "https://www.xiaohongshu.com/user/profile/user%s" % index,
            }
            for index in range(300)
        ]
        started = time.perf_counter()
        result = xhs._xhs_filter_comment_candidates(rows, log=FakeLogger(), strict=True)
        elapsed = time.perf_counter() - started
        self.assertEqual(len(result), 300)
        self.assertLess(elapsed, 0.05)
```

- [ ] **Step 2: Run tests and verify the RED state**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_xhs_lead_filtering.XhsLeadFilteringTests -v
```

Expected: fails because `_xhs_filter_comment_candidates` is not defined.

- [ ] **Step 3: Implement ranking, fingerprinting, and structured log helpers**

Add these helpers after `_xhs_prepare_comment()`:

```python
_XHS_INTENT_PRIORITY = {"高意向": 0, "中意向": 1, "咨询": 2, "普通": 3}


def _xhs_comment_rank(item):
    return (
        _XHS_INTENT_PRIORITY.get(item.get("intent"), 9),
        -int(item.get("diggCount") or 0),
    )


def _xhs_fingerprint(*values):
    raw = "\x1f".join(str(value or "") for value in values)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def _xhs_log_discard(event, item, reason, note_id, candidate_index, log=None, exc=None):
    item = item or {}
    user = compact_text(item.get("user") or item.get("u") or "", 0)
    text = compact_text(item.get("text") or item.get("c") or "", 0)
    profile = str(
        item.get("profileUrl")
        or item.get("profile")
        or item.get("userUrl")
        or item.get("user_url")
        or ""
    )
    context = {
        "reason": reason,
        "noteId": str(note_id or item.get("noteId") or ""),
        "candidateIndex": int(candidate_index),
        "userLength": len(user),
        "commentLength": len(text),
        "recordFingerprint": _xhs_fingerprint(profile, user, text),
    }
    if profile:
        context["profileFingerprint"] = _xhs_fingerprint(profile)
    json_log(
        log or logger,
        event,
        level="error" if exc is not None else "warning",
        exc=exc,
        **context,
    )
```

- [ ] **Step 4: Implement the strict filtering pipeline**

Add this function after `_xhs_log_discard()`:

```python
def _xhs_filter_comment_candidates(raw_items, note_id="", source=None, log=None, strict=None):
    strict = xhs_strict_lead_filter_enabled() if strict is None else bool(strict)
    source = source or {}
    kept = {}
    legacy_seen = set()
    legacy_items = []
    reason_counts = {}

    for idx, raw in enumerate(raw_items or []):
        try:
            item, reason = _xhs_prepare_comment(
                raw,
                note_id=note_id,
                source=source,
                idx=idx,
                strict=strict,
            )
        except Exception as exc:
            reason = "parse_failed"
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            _xhs_log_discard(
                "xhs_collected_record_parse_failed",
                raw if isinstance(raw, dict) else {},
                reason,
                note_id,
                idx,
                log=log,
                exc=exc,
            )
            continue
        if not item.get("text"):
            continue
        if not strict:
            key = (item.get("user") or "") + "|" + (item.get("text") or "")
            if key not in legacy_seen:
                legacy_seen.add(key)
                legacy_items.append(item)
            continue
        if reason:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            _xhs_log_discard(
                "xhs_collected_record_filtered",
                item,
                reason,
                note_id,
                idx,
                log=log,
            )
            continue

        profile = item["profileUrl"]
        previous = kept.get(profile)
        if previous is None:
            kept[profile] = (item, idx)
            continue
        previous_item, previous_index = previous
        if _xhs_comment_rank(item) < _xhs_comment_rank(previous_item):
            reason = "duplicate_profile_replaced"
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            _xhs_log_discard(
                "xhs_collected_record_deduplicated",
                previous_item,
                reason,
                note_id,
                previous_index,
                log=log,
            )
            kept[profile] = (item, idx)
        else:
            reason = "duplicate_profile"
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            _xhs_log_discard(
                "xhs_collected_record_deduplicated",
                item,
                reason,
                note_id,
                idx,
                log=log,
            )

    if not strict:
        return legacy_items
    json_log(
        log or logger,
        "xhs_collection_filter_summary",
        level="info",
        noteId=str(note_id or ""),
        candidateCount=len(raw_items or []),
        acceptedCount=len(kept),
        filteredCount=sum(reason_counts.values()),
        reasonCounts=reason_counts,
    )
    return [entry[0] for entry in kept.values()]
```

- [ ] **Step 5: Run the pipeline tests**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_xhs_lead_filtering.XhsLeadParsingTests tests.test_xhs_lead_filtering.XhsLeadFilteringTests -v
```

Expected: all tests pass. Logs are valid JSON, no raw sample PII appears, and the 300-row budget test stays below 50 ms.

- [ ] **Step 6: Record a checkpoint without committing**

Run:

```powershell
git diff --check -- backend/platform_adapters.py tests/test_xhs_lead_filtering.py
.venv-win\Scripts\python.exe -m py_compile backend\platform_adapters.py tests\test_xhs_lead_filtering.py
```

Expected: both commands succeed. Do not commit until documentation line numbers are final.

---

### Task 3: Browser Collection And Cross-Note Integration

**Files:**
- Modify: `tests/test_xhs_lead_filtering.py`
- Modify: `backend/platform_adapters.py:577-715`

**Interfaces:**
- Consumes: Task 2 `_xhs_filter_comment_candidates()`.
- Produces: strict `/api/xhs/comments` items with unchanged response field names.
- Produces: strict `/api/finder/discover` comments/leads with one record per canonical homepage.

- [ ] **Step 1: Add failing integration tests**

Add `inspect` and `unittest.mock` imports:

```python
import inspect
from unittest import mock
```

Add this class before the module main guard:

```python
class XhsLeadIntegrationTests(unittest.TestCase):
    def test_browser_collector_does_not_select_every_container_div(self):
        source = inspect.getsource(xhs.xhs_get_comments)
        self.assertNotIn(".comments-container div", source)
        self.assertNotIn(".comment-list div", source)
        self.assertIn("rawText", source)
        self.assertIn("_xhs_filter_comment_candidates", source)

    def test_discovery_deduplicates_same_profile_across_notes(self):
        videos = [
            {"work_url": "https://www.xiaohongshu.com/explore/note-a", "title": "A"},
            {"work_url": "https://www.xiaohongshu.com/explore/note-b", "title": "B"},
        ]
        profile = "https://www.xiaohongshu.com/user/profile/repeat"
        side_effect = [
            {"items": [{"user": "用户", "text": "想了解", "profileUrl": profile, "intent": "咨询", "diggCount": 30, "noteId": "note-a"}]},
            {"items": [{"user": "用户", "text": "价格多少", "profileUrl": profile + "?xsec_token=secret", "intent": "高意向", "diggCount": 1, "noteId": "note-b"}]},
        ]
        with mock.patch.object(xhs, "xhs_search_notes", return_value={"items": videos}), mock.patch.object(
            xhs, "xhs_get_comments", side_effect=side_effect
        ), mock.patch.object(xhs, "json_log"):
            result = xhs.discover_xhs_leads_by_keyword("丰田汽车", video_num=2)

        self.assertEqual(result["commentCount"], 1)
        self.assertEqual(result["leadCount"], 1)
        self.assertEqual(result["leads"][0]["text"], "价格多少")
        self.assertEqual(result["leads"][0]["profileUrl"], profile)

    def test_discovery_preserves_different_profiles_with_same_username(self):
        videos = [{"work_url": "https://www.xiaohongshu.com/explore/note-a"}]
        items = [
            {"user": "同名", "text": "价格", "profileUrl": "https://www.xiaohongshu.com/user/profile/a", "intent": "高意向"},
            {"user": "同名", "text": "怎么买", "profileUrl": "https://www.xiaohongshu.com/user/profile/b", "intent": "高意向"},
        ]
        with mock.patch.object(xhs, "xhs_search_notes", return_value={"items": videos}), mock.patch.object(
            xhs, "xhs_get_comments", return_value={"items": items}
        ), mock.patch.object(xhs, "json_log"):
            result = xhs.discover_xhs_leads_by_keyword("丰田汽车", video_num=1)
        self.assertEqual(result["leadCount"], 2)
```

- [ ] **Step 2: Run integration tests and verify the RED state**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_xhs_lead_filtering.XhsLeadIntegrationTests -v
```

Expected: the selector contract fails because broad container `div` selectors remain; cross-note dedup fails because the existing key is `user|text`.

- [ ] **Step 3: Replace the DOM evaluator with strict comment candidates**

Inside `xhs_get_comments()`, replace the evaluator selectors and row construction with this JavaScript. Keep the existing login/risk handling around it:

```javascript
(maxN) => {
  const clean = s => (s || '').replace(/[\t\r ]+/g, ' ').trim();
  const visible = el => {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 40 && r.height > 10 && st.display !== 'none' && st.visibility !== 'hidden';
  };
  const rows = [];
  const seen = new Set();
  const selectors = [
    '[class*="comment-item"]',
    '[class*="CommentItem"]',
    '[data-e2e*="comment"]'
  ];
  const nodes = Array.from(document.querySelectorAll(selectors.join(','))).filter(visible);
  for (const el of nodes) {
    const rawText = (el.innerText || el.textContent || '').trim();
    const flatText = clean(rawText.replace(/\n+/g, ' '));
    if (!flatText || flatText.length < 2 || flatText.length > 600) continue;
    if (/登录|打开小红书|验证码|隐私政策|服务协议/.test(flatText)) continue;
    const link = el.querySelector('a[href*="/user/profile/"]') || el.closest('a[href*="/user/profile/"]');
    let profile = '';
    try {
      profile = link ? new URL(link.getAttribute('href') || link.href, location.href).href : '';
    } catch (_) {}
    const key = profile + '|' + rawText;
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push({id: key.slice(0, 96), rawText, profile});
    if (rows.length >= maxN) break;
  }
  return rows;
}
```

- [ ] **Step 4: Collect unique raw candidates and filter once per note**

In `xhs_get_comments()`, replace incremental `user|text` appends with this shape:

```python
    raw_candidates = []
    candidate_seen = set()
    candidate_limit = min(limit * 3, 900)
```

For every `found` row, append only unseen raw candidate signatures:

```python
                for raw in found or []:
                    signature = (
                        str(raw.get("profile") or ""),
                        str(raw.get("rawText") or ""),
                    )
                    if signature in candidate_seen:
                        continue
                    candidate_seen.add(signature)
                    raw_candidates.append(raw)
                if len(raw_candidates) >= candidate_limit:
                    break
```

After the scroll loop and before deciding whether to capture a debug snapshot, run:

```python
            comments = _xhs_filter_comment_candidates(
                raw_candidates,
                note_id=note_id,
                source=source or {},
                log=logger,
            )[:limit]
            if not comments:
                debug = _debug_page_snapshot(page, data_dir or os.getcwd(), "xhs-comments")
```

Pass `candidate_limit`, not `limit`, as the `page.evaluate()` argument. Keep the existing result dictionary and risk/login logic unchanged.

- [ ] **Step 5: Reuse the same pipeline across notes**

In `discover_xhs_leads_by_keyword()`, remove the `seen` set and `user|text` filtering. Extend `comments` with every valid `res["items"]`, then add this line after the video loop:

```python
    comments = _xhs_filter_comment_candidates(comments, note_id="", log=logger)
```

Keep the existing intent sort and `leads` subset. This second pass canonicalizes query variants and selects the best record across notes.

- [ ] **Step 6: Run integration and focused regression tests**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_xhs_lead_filtering -v
.venv-win\Scripts\python.exe -m unittest tests.test_structured_log tests.test_douyin_multi_account -v
.venv-win\Scripts\python.exe -m py_compile backend\platform_adapters.py tests\test_xhs_lead_filtering.py
```

Expected: all new tests pass; existing structured logging and Douyin multi-account finder tests remain green; compilation exits 0.

- [ ] **Step 7: Re-run the fake-data end-to-end postprocessing smoke**

Run:

```powershell
.venv-win\Scripts\python.exe -c "import json,sys; sys.stdout.reconfigure(encoding='utf-8'); from backend.platform_adapters import _xhs_filter_comment_candidates; rows=[{'user':'无链接','text':'价格','profile':''},{'user':'.','text':'价格多少 07-17 黑龙江 赞 回复','profile':'https://www.xiaohongshu.com/user/profile/dot'},{'user':'🌙','text':'想了解','profile':'https://www.xiaohongshu.com/user/profile/moon'},{'user':'🌙','text':'价格多少','profile':'https://www.xiaohongshu.com/user/profile/moon','intent':'高意向'}]; result=_xhs_filter_comment_candidates(rows,note_id='note-smoke'); print(json.dumps(result,ensure_ascii=False))"
```

Expected: output contains exactly two records; `.` has comment `价格多少`, `🌙` keeps `价格多少`, and no record has an empty homepage.

- [ ] **Step 8: Record a checkpoint without committing**

Run:

```powershell
git diff --check -- backend/platform_adapters.py tests/test_xhs_lead_filtering.py
git status --short -- backend/platform_adapters.py tests/test_xhs_lead_filtering.py
```

Expected: no whitespace errors. Do not commit before final documentation and line-number synchronization.

---

### Task 4: Environment Contract And Production Documentation

**Files:**
- Modify: `backend/.env.example`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Documents: `XHS_STRICT_LEAD_FILTER_ENABLED=1` and emergency rollback semantics.
- Documents: final source/test line references and verification evidence.
- Does not change: OpenAPI, API reference, healthcheck, Docker topology, or database migration.

- [ ] **Step 1: Add the environment example**

Append this non-secret section to `backend/.env.example`:

```dotenv

# Xiaohongshu lead collection quality gate. Set to 0 only for emergency rollback.
XHS_STRICT_LEAD_FILTER_ENABLED=1
```

- [ ] **Step 2: Add deployment and rollback instructions**

Append this section to `docs/DEPLOYMENT.md`:

```markdown
## 小红书获客采集过滤

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `XHS_STRICT_LEAD_FILTER_ENABLED` | `1` | 开启主页校验、评论尾部清洗、用户名校验和主页级去重。仅在确认误过滤时临时设置为 `0/false/no/off`，修改后重启本地执行引擎。 |

该过滤运行在本地执行引擎，不新增端口、数据库、外部密钥、网络请求或 GPU 服务。紧急降级只关闭严格校验和主页级去重，不修改历史数据；完整回滚前先校验 `backups/xhs-lead-filtering-20260727/manifest.sha256`，再恢复归档中的 `backend/platform_adapters.py` 和相关文档。
```

- [ ] **Step 3: Capture final line numbers**

Run:

```powershell
rg -n '^def xhs_strict_lead_filter_enabled|^def _xhs_clean_comment_text|^def _xhs_prepare_comment|^def _xhs_filter_comment_candidates|^def xhs_get_comments|^def discover_xhs_leads_by_keyword' backend\platform_adapters.py
rg -n '^class XhsLeadParsingTests|^class XhsLeadFilteringTests|^class XhsLeadIntegrationTests' tests\test_xhs_lead_filtering.py
```

Expected: every symbol is reported exactly once. Use those reported final lines in the next step; do not estimate or copy pre-edit line numbers.

- [ ] **Step 4: Add the implementation index with final reported lines**

At the top of `docs/IMPLEMENTATION.md`, immediately after `# 实现索引`, add a `## 2026-07-27 小红书获客采集数据过滤` section. It must contain:

```markdown
- `backend/platform_adapters.py` 的严格过滤开关、评论尾部清洗、主页规范化和校验 helper 最终行号，说明无主页、空用户名、用户名等于评论的稳定原因码，以及 `.`/纯 emoji 保留规则。
- `backend/platform_adapters.py` 的过滤、SHA-256 指纹、逐条脱敏 JSON 日志和主页优先级归并 helper 最终行号，列出四个日志事件名，并说明解析异常带脱敏堆栈且不终止整批采集。
- `backend/platform_adapters.py` 的 `xhs_get_comments()` 和 `discover_xhs_leads_by_keyword()` 最终行号，说明已移除普通容器 `div` 候选并在单笔记、跨笔记两层按主页归并。
- `tests/test_xhs_lead_filtering.py` 三个测试类的最终行号，说明覆盖清洗边界、过滤规则、日志脱敏、回滚开关、性能预算、DOM 契约和跨笔记去重。
- 验证命令及实际通过数量；若真实页面冒烟未执行，明确写出原因。
- 回滚：设置 `XHS_STRICT_LEAD_FILTER_ENABLED=0` 并重启本地执行引擎可紧急降级；完整回滚使用已校验的修改前归档。本次不涉及数据库、OpenAPI 或 `migration.sql`。
```

Replace each prose “最终行号” description with the exact `path#Lstart-Lend` references reported by Step 3. Do not leave generic file-only references in the finished document.

- [ ] **Step 5: Complete troubleshooting after tests**

Extend the Phase 0 section added in Task 0 with the final reason codes and exact verification commands:

```markdown
- 过滤原因码：`missing_profile_url`、`invalid_profile_url`、`empty_user`、`user_equals_comment`；去重原因码：`duplicate_profile`、`duplicate_profile_replaced`。
- 日志排查：查询 `xhs_collected_record_filtered`、`xhs_collected_record_deduplicated`、`xhs_collected_record_parse_failed`、`xhs_collection_filter_summary`；日志只包含长度和 SHA-256 截断指纹，不包含用户原文或完整链接；解析异常日志额外包含脱敏堆栈。
- 验证：运行 `.venv-win\Scripts\python.exe -m unittest tests.test_xhs_lead_filtering tests.test_structured_log tests.test_douyin_multi_account -v`，再运行 `.venv-win\Scripts\python.exe -m py_compile backend\platform_adapters.py tests\test_xhs_lead_filtering.py`。
- 紧急降级：设置 `XHS_STRICT_LEAD_FILTER_ENABLED=0` 并重启本地执行引擎；降级会恢复兼容过滤行为，可能再次出现低质量结果，仅用于短期排障。
```

- [ ] **Step 6: Add changelog entries**

Under `## 2026-07-25` -> `### Fixed`, add:

```markdown
- 小红书获客采集不再把评论容器的普通子节点当作独立用户；无有效主页、空用户名、用户名等于评论的记录会在后端过滤，评论末尾时间、地区、作者、点赞和回复元信息会被清理，同一主页只保留意向最高且点赞优先的记录。
```

Under the same date's Operations section, add:

```markdown
- 本次小红书获客过滤只修改本地平台适配器、测试、环境示例和文档，不改变 API Schema、数据库或 `migration.sql`。每条淘汰记录写脱敏 JSON 日志；误过滤时可设置 `XHS_STRICT_LEAD_FILTER_ENABLED=0` 并重启本地执行引擎，完整回滚使用 `backups/xhs-lead-filtering-20260727/` 归档。
```

- [ ] **Step 7: Verify documentation consistency and preservation**

Run:

```powershell
rg -n 'XHS_STRICT_LEAD_FILTER_ENABLED|xhs_collected_record_filtered|xhs_collected_record_deduplicated|xhs_collected_record_parse_failed|xhs_collection_filter_summary' backend\.env.example docs\DEPLOYMENT.md docs\IMPLEMENTATION.md docs\TROUBLESHOOTING.md CHANGELOG.md
rg -n 'backend/platform_adapters.py#L[0-9]+(-L[0-9]+)?|tests/test_xhs_lead_filtering.py#L[0-9]+(-L[0-9]+)?' docs\IMPLEMENTATION.md
git diff --check -- backend/.env.example CHANGELOG.md docs/DEPLOYMENT.md docs/IMPLEMENTATION.md docs/TROUBLESHOOTING.md
```

Expected: the environment variable appears in env/deployment/troubleshooting/changelog, all three events appear in implementation/troubleshooting, final line references match `path#Lx-Ly`, and no whitespace errors exist. Compare the pre-edit and current tracked-doc diffs to confirm all user changes remain.

---

### Task 5: Final Verification, Read-Only Live Smoke, And Handoff

**Files:**
- Verify all files listed above.
- Do not modify runtime account data, browser cookies, central state, or database files.

**Interfaces:**
- Produces: automated verification evidence, optional read-only live evidence, rollback verification, and final risk statement.

- [ ] **Step 1: Run the focused full test gate**

Run:

```powershell
.venv-win\Scripts\python.exe -m unittest tests.test_xhs_lead_filtering tests.test_structured_log tests.test_douyin_multi_account -v
```

Expected: all listed tests pass with no warnings or tracebacks. Record the actual test count in `docs/IMPLEMENTATION.md`.

- [ ] **Step 2: Run compilation and diff checks**

Run:

```powershell
.venv-win\Scripts\python.exe -m py_compile backend\platform_adapters.py tests\test_xhs_lead_filtering.py
git diff --check
```

Expected: both commands exit 0.

- [ ] **Step 3: Run the deterministic fake-data smoke again**

Repeat Task 3 Step 7.

Expected: exactly two valid canonical-profile records, no metadata suffix, and the higher-priority duplicate retained. Capture the structured log event names without copying raw user data into docs.

- [ ] **Step 4: Attempt a read-only live Xiaohongshu smoke when the local profile is ready**

First run a readiness check only:

```powershell
.venv-win\Scripts\python.exe -c "from backend.platform_adapters import xhs_profile_ready; print('ready=' + str(bool(xhs_profile_ready('backend/datas'))).lower())"
```

If it prints `ready=true`, call the existing read-only comments path against one already known test note and request at most 20 comments. Do not call comment publish, material publish, outreach, login mutation, or any external write endpoint. Verify every returned item has a canonical `/user/profile/` URL, non-empty username, username different from comment, and no terminal UI metadata.

If readiness is false, IP risk `300012` appears, or sandbox/network policy blocks the page, stop the live smoke and record the exact limitation in `docs/IMPLEMENTATION.md`; deterministic tests remain the release gate.

- [ ] **Step 5: Verify rollback artifacts remain unchanged**

Repeat Task 0 Step 5.

Expected: no output. Confirm `backups/xhs-lead-filtering-20260727/` is ignored and not staged.

- [ ] **Step 6: Review the final change set without staging unrelated work**

Run:

```powershell
git status --short
git diff -- backend/platform_adapters.py backend/.env.example CHANGELOG.md docs/DEPLOYMENT.md docs/IMPLEMENTATION.md docs/TROUBLESHOOTING.md tests/test_xhs_lead_filtering.py
git diff --cached --name-only
```

Expected: only intended work appears in target-file diffs, pre-existing user changes in tracked docs are still present, and the index is empty. Do not stage or commit implementation files unless the user explicitly approves a final commit after reviewing the verified diff.

- [ ] **Step 7: Final handoff**

Report:

- What changed in collection, validation, deduplication, and logging.
- Exact test/compile/smoke commands and observed counts.
- Whether the read-only live smoke ran; if not, why.
- The emergency environment rollback and full archive restore paths.
- Remaining risk: future Xiaohongshu DOM class changes may reduce collected quantity, but strict validation fails closed instead of returning fake leads.
