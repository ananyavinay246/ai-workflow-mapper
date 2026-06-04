# AI Workflow Mapper Implementation Notes

Use this file to record implementation decisions that clarify or intentionally deviate from the specification.

## Decisions

### Domain `input` Fields (POST /jobs)

`schemas/input.schema.json` declares `input: {additionalProperties: true}` — the JSON schema is intentionally open.
The implementation narrows it in `src/ai_workflow_mapper/workflow/domain.py`:

```
documents: list of {filename (str), content_b64 (base64 str), source_type? (str, default "document")}
description: str | None   — optional free-text workflow description
```

Unknown fields in `input` are silently ignored (forward-compatible; `extra="ignore"`).

### Input Format Routing (Input Normalizer)

The Input Normalizer (`src/ai_workflow_mapper/workflow/normalizer.py`) dispatches by file extension:

- `.txt`, `.md`, `.json`, `.pdf`, `.docx` → `document_loader.extract_text`
- `.xml` (BPMN, draw.io) → decoded as raw UTF-8 text; `parser="xml-text"`
- `.csv` (Jira/Asana/Notion tool exports) → pipe-delimited text table via stdlib `csv`; `parser="csv"`
- `.vsdx` (Visio) → unzipped in-memory, Visio page XML text extracted via `xml.etree.ElementTree`; `parser="vsdx"`

### Deferred Input Sources

URL ingestion (`http://`, `https://`) is not yet implemented. Documents with URL filenames are
added to `result.skipped` with `reason="URL ingestion not yet supported"`. A warning is recorded.
Implement in a later slice using `httpx` + an HTML-to-text library.

### Trust-Level Tagging

`<process_content trust_level="untrusted">` wrapping (required by LLM adapter security gate) is
NOT applied by the Input Normalizer. The normalizer returns plain extracted text. The Process
Extractor (next slice) is responsible for wrapping content before any LLM call.

### LLM Adapter — `LLM_API_KEY` Environment Variable

`LocalLLMAdapter` reads `os.environ["LLM_API_KEY"]` at construction and raises `RuntimeError`
immediately if it is absent. There is no graceful fallback. Any code path that instantiates the
adapter (including the Process Extractor slice) requires this variable to be set before the
server starts.

### LLM Adapter — `complete_structured` Expects Bare JSON

`_complete_structured` calls `json.loads()` directly on the model's raw text response. If the
model wraps its output in ` ```json ` fences (Claude's default without explicit instruction),
parsing fails with `llm_schema_validation_failed`. The Process Extractor's system prompt **must**
explicitly instruct the model to respond with raw JSON only, with no surrounding text or fences.

### LLM Adapter — Per-Call Cost Gate Defaults to $1.00

`DEFAULT_COST_LIMIT_USD = 1.0` is a pre-call estimated cost check (not a running budget tracker).
A single call estimated to exceed $1.00 raises `llm_cost_limit_exceeded` and is never sent.
The estimate is based on character count ÷ 4 ≈ tokens. Large document sets sent in a single
prompt may trip this; the Extractor must either chunk documents or raise the limit via
`config.settings["cost_limit_usd"]`.

### Document Loader — 10 MB Per-Document Size Limit

`LocalDocumentLoader.DEFAULT_MAX_BYTES = 10 * 1024 * 1024`. Documents exceeding this return
`document_too_large`, which the normalizer catches and adds to `result.skipped`. This matches
the spec's stated limit and is enforced in the `load_document` operation only (not
`extract_text` directly — the normalizer uses `extract_text`, so the size check happens inside
the loader's `_decode_bytes` helper which is shared across operations).

### Document Loader — Image-Only PDFs Produce Empty Text (Not Skipped)

If all pages in a PDF are image-based, `pypdf` returns empty strings per page with a warning
`"Page N yielded no text (may be image-based)"`. The document is **not** skipped — it is
returned to the normalizer with `text=""` and the warning surfaced in `result.warnings`. The
Process Extractor will receive an empty string for such documents and must handle it without
crashing (e.g., skip documents with zero char_count).

### Document Loader — DOCX Extraction Coverage

`_extract_text_docx` extracts body content in document order (paragraphs and tables
interleaved via `doc.element.body` iteration), section headers (prepended), and section
footers (appended). Table rows are rendered as pipe-separated cells (`cell1 | cell2`),
matching the CSV normalizer convention. Sections linked to a previous section are skipped
to avoid duplicate header/footer text.

**Still not extracted**: text inside `<w:drawing>` shapes and text boxes. These require
DrawingML namespace traversal and are deferred to a later slice.

### Document Loader — `content_bytes_b64` Field Name in Loader Request

The loader's `_decode_bytes` reads from `inp["content_bytes_b64"]`. The domain model uses the
field name `content_b64`. The normalizer bridges this by constructing the loader request as
`{"filename": doc.filename, "content_bytes_b64": doc.content_b64}`. Any new code calling the
loader directly must use `content_bytes_b64` as the key, not `content_b64`.

### API — POST /jobs Processes Synchronously Despite 202 Status

`process()` runs in the request handler and blocks until complete. The job transitions
`accepted → succeeded/failed` within the same request. The 202 status and polling endpoint
(`GET /jobs/{job_id}`) exist to satisfy the OpenAPI contract but the result is already final
in the POST response body. Background threading is deferred; this is a deliberate simplification
for the local implementation.

### API — RequestValidationError Returns 400, Not FastAPI's Default 422

A custom exception handler overrides FastAPI's default `422 Unprocessable Entity` to return
`400 Bad Request` with an `ApiError` body, matching `errors.schema.json`. Any future middleware
or additional exception handlers must preserve this mapping.

### API — `response_model_exclude_none=True` on Job Endpoints

Both `POST /jobs` and `GET /jobs/{job_id}` use `response_model_exclude_none=True`. Optional
array fields (`warnings`, `citations`, `artifacts`) are omitted from responses rather than
serialized as `null`, because `output.schema.json` types them as `array` (not `array | null`).
New job endpoints must apply the same decorator or schema validation will break.

### API — Job Store Is In-Memory with No Persistence or TTL

`api/store.py` uses a module-level dict. Jobs are lost on server restart. The store grows
unboundedly — there is no eviction policy. Acceptable for local development; must be replaced
with a persistent store before production deployment.

## Approved Deviations

- No deviations have been approved yet.

## Agent Notes

- Agents must read specification_ai_workflow_mapper.md before editing implementation code.
- Agents must update this file when they make a contract-affecting decision.
- Agents must not silently invent fields that conflict with schemas/ or openapi.yaml.
