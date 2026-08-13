### Task 5: Production Docs, Smoke Notes, And Release Records

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/TROUBLESHOOTING.md`
- Modify: `docs/IMPLEMENTATION.md`
- Modify: `CHANGELOG.md`
- Modify: `migration.sql`

**Interfaces:**
- Consumes: final code line numbers from Tasks 1-4.
- Produces: production docs consistent with code.

- [ ] **Step 1: Update architecture doc**

Add a concise note to `docs/ARCHITECTURE.md`:

```markdown
### 本地执行端替换网页

本地执行端可在 `MATRIX_REPLACEMENT_WEB_ENABLED=1` 时提供 `/replacement` 页面。该页面由 `backend/api_server.py` 直接服务，复用本机账号、素材目录和替换任务逻辑；它不是独立 `frontend/` Web 产品面，也不恢复旧 `/admin` 页面。视频替换和图文替换任务状态写入本地 JSON，远程模型输入必须先转换为可访问 HTTPS 媒体 URL。
```

- [ ] **Step 2: Update deployment doc**

Add to the environment variable table in `docs/DEPLOYMENT.md`:

```markdown
| `MATRIX_REPLACEMENT_WEB_ENABLED` | 本地执行端是否开放 `/replacement` 替换网页 | `0` | 设置为 `1` 后重启本地执行端生效；关闭后页面和 start API 返回 `replacement_web_disabled` |
```

- [ ] **Step 3: Update troubleshooting with Phase 0 result**

Add to `docs/TROUBLESHOOTING.md`:

```markdown
## 本地 /replacement 替换网页 Phase 0

症状：`GET /replacement` 返回 `replacement_web_disabled`。

处理：确认本地执行端环境变量 `MATRIX_REPLACEMENT_WEB_ENABLED=1`，并重启本地执行端。该开关默认关闭，用于快速回滚本地替换网页入口。

Phase 0 冒烟：使用假视频链接和假人物图调用 `/api/replacement/video/start`，返回 `rvw_` job；使用假小红书链接和两张假图片调用 `/api/replacement/note/start`，返回 `xnr_` job 和三套文案候选。Phase 0 不提交真实远程模型，不产生真实 LK888 费用。
```

- [ ] **Step 4: Update changelog**

Add near the top of `CHANGELOG.md`:

```markdown
## 2026-08-04 本地执行端替换网页 MVP

- 本地执行端新增可开关的 `/replacement` Phase 0 页面，包含“视频替换”和“图文替换”两个标签页；页面只创建本地替换任务并展示状态，不恢复独立 Web 前端、不接真实发布、不做资产库管理。
- 新增 `/api/replacement/video/start`、`/api/replacement/video/job`、`/api/replacement/note/start`、`/api/replacement/note/job` 本地接口；默认由 `MATRIX_REPLACEMENT_WEB_ENABLED=0` 关闭，开启后需重启本地执行端。
- RED/GREEN 覆盖 feature gate、页面 HTML、Phase 0 任务创建、错误校验、OpenAPI/API reference 和日志脱敏边界；`py_compile` 通过。
- 本次影响本地执行端、OpenAPI/API 文档和本地 JSON 任务骨架；不改变中心服数据库、Docker 镜像结构、远程 AI Canvas 部署或真实 LK888 提交逻辑。回滚时关闭 `MATRIX_REPLACEMENT_WEB_ENABLED` 并恢复相关代码/文档即可。
```

- [ ] **Step 5: Update migration no-op**

Append to `migration.sql`:

```sql
-- 2026-08-04 local replacement web MVP: no database schema change.
-- Local /replacement Phase 0 jobs are stored as local JSON under the agent data directory.
```

- [ ] **Step 6: Update implementation line references**

After final code edits, compute exact line references:

```powershell
rg -n "MATRIX_REPLACEMENT_WEB_ENABLED|def replacement_web_enabled" backend\platform_features.py
rg -n "def replacement_page_html|def start_video_job|def start_note_job|def load_job|def job_response" backend\replacement_web.py
rg -n "path == \"/replacement\"|/api/replacement/video/start|/api/replacement/note/start|html_response" backend\api_server.py
rg -n "ReplacementWebFeatureGateTests|ReplacementWebModuleTests|ReplacementApiServerRouteTests|ReplacementWebDocumentationTests" tests\test_replacement_web_mvp.py
```

Add a section to `docs/IMPLEMENTATION.md` using exact line references from the commands above. Each bullet must use the concrete `path#Lnumber-Lnumber` format from the final code after formatting. The section must cover:

- `backend/platform_features.py` feature gate lines.
- `backend/replacement_web.py` HTML, validation, job persistence, start helpers, and response helper lines.
- `backend/api_server.py` HTML route, status routes, start routes, and structured logging lines.
- `tests/test_replacement_web_mvp.py` feature gate, module, route, and docs contract test lines.
- The exact unittest, OpenAPI test, `py_compile`, and Phase 0 smoke commands actually run.
- Rollback instructions: close `MATRIX_REPLACEMENT_WEB_ENABLED`, restart the local execution server, and revert touched code/tests/docs/no-op migration if needed.

Before committing, scan `docs/IMPLEMENTATION.md` for non-final line markers:

```powershell
rg -n "L\\.\\.\\.|Lx|TODO|TBD" docs\IMPLEMENTATION.md
```

Expected: no matches.

- [ ] **Step 7: Run docs tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

Do not commit in this task. The user confirmed per-task commits are disabled; the controller will make one final commit only after all code, docs, OpenAPI, and `docs/IMPLEMENTATION.md` line references are stable. Do not run `git add` or `git commit` for this task.
```

---


