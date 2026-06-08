# AI Workflow Mapper Implementation Notes

Use this file to record implementation decisions that clarify or intentionally deviate from the specification.

## Decisions

### Domain `input` and `options` (POST /jobs)

Public contracts:

- `schemas/input.schema.json` → `input` refs `workflow_input.schema.json`, `options` refs `job_options.schema.json`.
- Pydantic: `WorkflowInput`, `JobOptions` in `workflow/domain.py`; wired via `api.models.JobInput`.

`workflow_input`: `documents[]` (`filename`, `content_b64`, `source_type` enum), optional `description`.

`job_options`: `output_format`, `mode`, optional `diagram_types`, `diagram_formats`, `model_profile`, `max_cost_usd`, `require_human_review`.

`extra="forbid"` on domain models — unknown fields are rejected at API validation.

### Domain `result` (job output)

- `schemas/output.schema.json` → `result` is `null` or `workflow_result.schema.json` (or error object on `failed`).
- Current implementation returns `WorkflowResult` with required `normalization_summary` only; `process_graph` and `analysis` are optional until later slices.
- `process_extraction.schema.json` is for LLM output; `process_graph.schema.json` and `analysis_findings.schema.json` are defined but not yet populated by the processor.

### Input Format Routing (Input Normalizer)

The Input Normalizer (`src/ai_workflow_mapper/workflow/normalizer.py`) dispatches by file extension:

- `.txt`, `.md`, `.json`, `.pdf`, `.docx` → `document_loader.extract_text`
- `.xml` (BPMN, draw.io) → decoded as raw UTF-8 text; `parser="xml-text"`
- `.csv` (Jira/Asana/Notion tool exports) → pipe-delimited text table via stdlib `csv`; `parser="csv"`
- `.vsdx` (Visio) → unzipped in-memory, Visio page XML text extracted via `xml.etree.ElementTree`; `parser="vsdx"`

### Post-Extraction Text Cleaning

After `document_loader.extract_text` returns raw text, the Input Normalizer runs
`workflow/text_cleaner.clean_extracted_text()` before building `NormalizedDocument`. Cleaning
is deterministic (stdlib only: `re`, `unicodedata`) and does not change public contracts.

**Pipeline order:**

1. Unicode repair — NFKC normalization, strip BOM/NUL/zero-width chars, fix PDF ligatures and
   common mojibake sequences.
2. Header/footer removal — drop explicit page-number lines (`Page X of Y`, etc.) and lines that
   repeat on ≥50% of PDF pages (split on `\f` from the loader).
3. Line-wrap fixes — de-hyphenate PDF line breaks, normalize bullet glyphs to `-`, collapse
   consecutive duplicate lines.
4. Table flattening — convert pipe-separated (DOCX/CSV), tab-separated, or space-aligned row
   blocks into markdown tables (`| col |` + `| --- |` separator). Existing markdown tables are
   left unchanged.
5. Whitespace pass — strip trailing line spaces, collapse blank lines, trim document edges.

**Parser guards:** `parser="json"` runs step 1 and outer strip only — JSON structure is not
altered. All other parsers run the full pipeline.

**Observability:** `NormalizedDocument.metadata["cleaning"]` records `chars_before`,
`chars_after`, `pages_processed`, `footers_removed`, and `tables_converted`. If cleaning removes
>40% of characters, a warning is appended: `"Text cleaning removed a large portion of extracted
content; review source document"`.

**Limitations:** Table detection is heuristic; space-aligned PDF tables may not convert. Repeating
header detection may remove legitimate repeated section titles on multi-page documents when they
appear on most pages. OCR for image-only PDFs and DrawingML text boxes remain deferred.

### Deferred Input Sources

URL ingestion (`http://`, `https://`) is not yet implemented. Documents with URL filenames are
added to `result.skipped` with `reason="URL ingestion not yet supported"`. A warning is recorded.
Implement in a later slice using `httpx` + an HTML-to-text library.

### Trust-Level Tagging

`<process_content trust_level="untrusted">` wrapping is applied by the Process Extractor
(`workflow/extractor.py`) before every LLM call. The normalizer returns plain text; the extractor
wraps each document using the adapter's exact opening tag, with `[source: filename]` on the first
line inside the tag. The optional `description` field is wrapped the same way with
`[source: description]`.

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
The estimate is based on character count ÷ 4 ≈ tokens.

### Process Extractor — Cost Limit Default $5.00

`ProcessExtractor` defaults to `cost_limit_usd=5.0` (not the adapter's $1.00) because a
20-document corpus routinely exceeds the $1.00 gate in a single combined call. Callers may
override via `JobOptions.max_cost_usd`. The adapter's own default is deliberately kept low to
protect isolated module calls; the extractor raises it explicitly for multi-document workloads.
Document this in IMPLEMENTATION_NOTES when changing the default.

### Process Extractor — Empty Corpus Guard

When all normalized documents have `char_count == 0` (e.g. all image-only PDFs) or no documents
are provided at all, `ProcessExtractor.extract()` returns an empty `ProcessExtraction` with a
warning and does **not** call the LLM. This keeps the pipeline valid and avoids unnecessary API
charges.

### Process Extractor — `description` Parameter

`ProcessExtractor.extract()` takes an optional `description: str | None` argument (not from
`JobOptions`). The processor passes `job_input.input.description` here. This keeps `JobOptions`
focused on execution settings and mirrors the domain model where description lives on `WorkflowInput`.

### ProcessGraph Serialization

`WorkflowResult.process_graph` is typed `ProcessGraph | None`. In `processor.py`, the result is
serialized with `model_dump(mode="json", exclude_none=True)` so nested Pydantic models (including
`ProcessGraph`, `GraphEdge` with `from` alias) are correctly serialized. `GraphEdge` uses
`Field(alias="from")` — always serialize with `by_alias=True` when the output must match the JSON
schema field name `"from"`.

### API — No LLM Call When `LLM_API_KEY` Not Set

`processor.py` checks `os.environ.get("LLM_API_KEY")` before constructing `LocalLLMAdapter`. When
the key is absent, extraction and graph build are skipped and a warning is appended to
`normalization_summary.warnings`. This preserves the existing API tests (which use an empty
documents list) without requiring the env var in CI.

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
