### Task 4: OpenAPI And API Reference

**Files:**
- Modify: `docs/openapi.yaml`
- Modify: `docs/API_REFERENCE.md`
- Modify: `tests/test_replacement_web_mvp.py`

**Interfaces:**
- Consumes: route contracts implemented in Task 3.
- Produces: documented API contract for `/replacement` and `/api/replacement/*`.

- [ ] **Step 1: Write failing documentation contract tests**

Append to `tests/test_replacement_web_mvp.py`:

```python
class ReplacementWebDocumentationTests(unittest.TestCase):
    def test_openapi_documents_replacement_api_paths(self):
        text = (ROOT / "docs" / "openapi.yaml").read_text(encoding="utf-8")

        self.assertIn("/api/replacement/video/start:", text)
        self.assertIn("/api/replacement/video/job:", text)
        self.assertIn("/api/replacement/note/start:", text)
        self.assertIn("/api/replacement/note/job:", text)
        self.assertIn("ReplacementVideoStartResponse", text)
        self.assertIn("ReplacementNoteJobResponse", text)

    def test_api_reference_documents_local_only_replacement_page(self):
        text = (ROOT / "docs" / "API_REFERENCE.md").read_text(encoding="utf-8")

        self.assertIn("GET /replacement", text)
        self.assertIn("MATRIX_REPLACEMENT_WEB_ENABLED", text)
        self.assertIn("本地执行端", text)
        self.assertIn("POST /api/replacement/video/start", text)
        self.assertIn("POST /api/replacement/note/start", text)
```

- [ ] **Step 2: Run docs tests and verify they fail**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp.ReplacementWebDocumentationTests -v
```

Expected: FAIL because docs do not yet include the new paths.

- [ ] **Step 3: Update `docs/openapi.yaml`**

Add these paths under `paths:`:

```yaml
  /api/replacement/video/start:
    post:
      summary: Start a local video replacement Phase 0 job
      requestBody:
        required: true
        content:
          multipart/form-data:
            schema:
              $ref: '#/components/schemas/ReplacementVideoStartRequest'
      responses:
        '200':
          description: Job created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ReplacementVideoStartResponse'
        '400':
          description: Invalid replacement request
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'

  /api/replacement/video/job:
    get:
      summary: Read a local video replacement job
      parameters:
        - in: query
          name: id
          required: true
          schema:
            type: string
            pattern: '^rvw_[0-9a-f]{24}$'
      responses:
        '200':
          description: Video replacement job status
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ReplacementVideoJobResponse'

  /api/replacement/note/start:
    post:
      summary: Start a local image-note replacement Phase 0 job
      requestBody:
        required: true
        content:
          multipart/form-data:
            schema:
              $ref: '#/components/schemas/ReplacementNoteStartRequest'
      responses:
        '200':
          description: Job created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ReplacementNoteStartResponse'
        '400':
          description: Invalid replacement request
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'

  /api/replacement/note/job:
    get:
      summary: Read a local image-note replacement job
      parameters:
        - in: query
          name: id
          required: true
          schema:
            type: string
            pattern: '^xnr_[0-9a-f]{24}$'
      responses:
        '200':
          description: Image-note replacement job status
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ReplacementNoteJobResponse'
```

Add these schemas under `components.schemas`. If `ErrorResponse` already exists, reuse it and do not duplicate it:

```yaml
    ReplacementVideoStartRequest:
      type: object
      required: [sourceUrl, characterImage]
      properties:
        sourceUrl:
          type: string
          format: uri
        characterImage:
          type: string
          format: binary
        productImage:
          type: string
          format: binary
        sceneImage:
          type: string
          format: binary
        script:
          type: string
        sellingPoints:
          type: string

    ReplacementVideoStartResponse:
      type: object
      required: [ok, jobId, taskType, status, stage]
      properties:
        ok:
          type: boolean
        jobId:
          type: string
          pattern: '^rvw_[0-9a-f]{24}$'
        taskType:
          const: video
        status:
          type: string
        stage:
          type: string

    ReplacementVideoJobResponse:
      type: object
      required: [ok, jobId, taskType, status, stage, result]
      properties:
        ok:
          type: boolean
        jobId:
          type: string
        taskType:
          const: video
        status:
          type: string
        stage:
          type: string
        progressText:
          type: string
        result:
          type: object
          additionalProperties: true
        error:
          type: string

    ReplacementNoteStartRequest:
      type: object
      required: [sourceUrl, replacementImages, businessName]
      properties:
        sourceUrl:
          type: string
          format: uri
        replacementImages:
          type: array
          items:
            type: string
            format: binary
        businessName:
          type: string
        region:
          type: string
        sellingPoints:
          type: string
        audience:
          type: string
        tone:
          type: string

    ReplacementNoteStartResponse:
      type: object
      required: [ok, jobId, taskType, status, stage]
      properties:
        ok:
          type: boolean
        jobId:
          type: string
          pattern: '^xnr_[0-9a-f]{24}$'
        taskType:
          const: note
        status:
          type: string
        stage:
          type: string

    ReplacementNoteJobResponse:
      type: object
      required: [ok, jobId, taskType, status, stage, imageSlots, copyCandidates]
      properties:
        ok:
          type: boolean
        jobId:
          type: string
        taskType:
          const: note
        status:
          type: string
        stage:
          type: string
        progressText:
          type: string
        imageSlots:
          type: array
          items:
            type: object
            additionalProperties: true
        copyCandidates:
          type: array
          items:
            type: object
            additionalProperties: true
        draftMaterialId:
          type: string
        error:
          type: string
```

- [ ] **Step 4: Update `docs/API_REFERENCE.md`**

Add a section near the local execution API sections:

```markdown
## 本地执行端替换网页 MVP

### GET /replacement

本地执行端内嵌 HTML 页面，仅在 `MATRIX_REPLACEMENT_WEB_ENABLED=1` 时开放。该页面不是独立产品 Web 前端，不依赖 `frontend/` 工程，也不恢复旧 `/admin` 页面。页面包含“视频替换”和“图文替换”两个标签页。

关闭开关时返回：

```json
{"ok": false, "error": "replacement_web_disabled"}
```

### POST /api/replacement/video/start

`multipart/form-data`。字段：`sourceUrl`、`characterImage`、`productImage`、`sceneImage`、`script`、`sellingPoints`。Phase 0 仅创建本地 `rvw_` 任务，不提交真实远程模型。

### GET /api/replacement/video/job

查询 `rvw_` 本地任务状态。

### POST /api/replacement/note/start

`multipart/form-data`。字段：`sourceUrl`、`replacementImages`、`businessName`、`region`、`sellingPoints`、`audience`、`tone`。Phase 0 复用图文同款预览骨架生成 `xnr_` 任务和三套文案候选。

### GET /api/replacement/note/job

查询 `xnr_` 本地图文替换任务状态，返回图片槽位和文案候选的安全子集。

所有接口日志必须脱敏来源链接 query、Cookie、Authorization、签名 URL 和 base64 图片内容。
```

- [ ] **Step 5: Run docs tests and OpenAPI contract tests**

Run:

```powershell
.\.venv-win\Scripts\python.exe -m unittest tests.test_replacement_web_mvp.ReplacementWebDocumentationTests -v
.\.venv-win\Scripts\python.exe -m unittest tests.test_openapi_contract -v
```

Expected: PASS. If `tests.test_openapi_contract` fails because the schema shape must match an existing helper convention, adjust `docs/openapi.yaml` only, without weakening the new replacement tests.

- [ ] **Step 6: Commit**

Do not commit in this task. The user confirmed per-task commits are disabled; the controller will make one final commit only after all code, docs, OpenAPI, and `docs/IMPLEMENTATION.md` line references are stable. Do not run `git add` or `git commit` for this task.


---


