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
- `WorkflowResult` includes `normalization_summary` (required), optional `process_graph`, and optional partial `analysis` (`analysis_findings` with only populated sections, e.g. `bottlenecks`).
- `process_extraction.schema.json` is for LLM structured extraction output only.

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

### Mermaid Diagram Generator

After `ProcessGraphBuilder`, the processor optionally runs `MermaidDiagramGenerator`
(`workflow/diagram_generator.py`) when `JobOptions.diagram_formats` contains `"mermaid"`.

**Opt-in:** If `diagram_formats` is omitted, no diagrams are generated (backward compatible).
CLI: `python -m ai_workflow_mapper.cli.submit_job --mermaid ...` sets `diagram_formats: ["mermaid"]`.

**Default diagram types when enabled:** `flowchart` and `swimlane` unless `diagram_types` narrows
the set. `value_stream` and `entity_relationship` are not implemented for Mermaid yet — they add
a job-level warning and are skipped.

**Output location:** Artifacts appear on `JobOutput.artifacts[]` (not inside `workflow_result`).
Each entry matches `diagram_artifact.schema.json` with `type: "diagram"`, `format: "mermaid"`,
inline `content`, relative `path` under `artifacts/{request_id}/`, and `checksum: sha256:...`.
Files are written locally by `platform/local/artifact_writer.py`.

**Rendering:** `workflow/mermaid_renderer.py` maps graph node types to Mermaid shapes (start/end
stadium, task rectangle, decision diamond, handoff double-border). Edges mirror `process_graph.edges`
exactly — no invented transitions. Swimlanes use Mermaid `subgraph` blocks per actor.

**Validation:** Slice 1 performs structural checks (header, declared nodes, edge endpoints). Full
Mermaid parser validation (spec quality gate) is deferred to eval harness / optional CI with
`@mermaid-js/mermaid-cli`.

**Processor return type:** `process()` returns `JobProcessResult(result, artifacts, citations, warnings)`.
Diagram warnings are job-level (`JobOutput.warnings`), not `normalization_summary.warnings`.

**PNG export (Kroki):** When `diagram_formats` includes `"png"`, each Mermaid diagram is POSTed to
the Kroki API (`KROKI_BASE_URL`, default `https://kroki.io`) and saved as `flowchart.png` /
`swimlane.png` under `artifacts/{request_id}/`. Requires network access. Kroki failures add a
job-level warning and do not fail the job. CLI: `--mermaid --png`. PNG artifacts omit inline
`content` (binary); use `path` to read the file.

**Kroki timeout:** The HTTP client waits up to `KROKI_TIMEOUT_S` seconds per diagram (default
`60`). This is a local client limit, not a Kroki server hard cap. Large or complex Mermaid graphs
on the public `kroki.io` instance may need a higher value (e.g. `120`). CLI `--timeout` applies
only to `--no-local` API submission, not Kroki rendering.

### Bottleneck Analyzer

After `ProcessGraphBuilder`, when `process_graph` is non-empty, the processor runs
`BottleneckAnalyzer` (`workflow/bottleneck_analyzer.py`) using graph heuristics
(`workflow/bottleneck_heuristics.py`) and document quote matching
(`workflow/evidence_matcher.py`).

**Activation:** Same gate as diagram generation — requires a non-empty `process_graph`. No new
`job_options` flag; `mode` controls LLM depth only.

**Detection (deterministic):** Candidates are task/decision nodes flagged by:

- High inbound edge count (`in_degree >= 2`) or incoming edge from a `handoff` node
- Queue/approval keywords in the label (`approve`, `review`, `hold`, `queue`, `wait`, …)
- Single-point-of-failure: sole actor on the longest start→end path with downstream fan-out
- Critical-path hub: on longest path with `out_degree >= 2`

**Severity:** `Critical` / `Moderate` / `Minor` from critical-path membership, signal strength,
and inbound handoffs. Enum casing matches `analysis_findings.schema.json` exactly.

**Evidence:** `EvidenceMatcher` searches normalized document text for a substring of the step
label. If no match, the finding is still emitted with `evidence: []` and an analyzer warning.
Quotes are never invented.

**Citations:** Each evidence item is promoted to `JobOutput.citations[]` with
`finding_id=bn-{node_id}`, `node_id`, and `trust_level="untrusted"`.

**LLM enrichment (`thorough` mode only):** When `JobOptions.mode == "thorough"` and
`LLM_API_KEY` is set, `complete_structured` refines `description`, `impact`, and
`root_cause_hypothesis`. LLM-supplied quotes are post-validated against normalized documents;
ungrounded quotes are dropped. On LLM failure, heuristic findings are preserved with a warning.

**Partial analysis output:** Only populated analysis sections are included; other
`analysis_findings` sections are omitted from serialized output.

**Known limitations:** In-degree may be inflated when the graph builder emits redundant
sequential + handoff edges. `require_human_review` / `needs_review` status for Critical findings
is deferred to a follow-up slice.

**Processor return type:** `process()` returns `JobProcessResult(result, artifacts, citations, warnings)`.
Bottleneck warnings are job-level (`JobOutput.warnings`).

### Redundancy Detector

After `ProcessGraphBuilder`, when `process_graph` is non-empty, the processor runs
`RedundancyAnalyzer` (`workflow/redundancy_analyzer.py`) using graph/text heuristics
(`workflow/redundancy_heuristics.py`, `workflow/label_similarity.py`) and document quote
matching (`workflow/evidence_matcher.py`).

**Activation:** Same gate as Bottleneck Analyzer. No new `job_options` flag; `mode` controls
LLM depth only.

**Detection (deterministic):**

- **Duplicate approval steps:** consecutive task/decision nodes whose labels match approval/review keywords
- **Duplicate system entry:** pairs of data-entry steps with different `tool` values and shared data-subject tokens (`customer`, `order`, `invoice`, …)
- **Duplicate information requests:** same `actor_id`, label Jaccard similarity ≥ 0.65, excluding consecutive duplicate-approval pairs
- **Overlapping roles:** different `actor_id`, both tasks, label similarity ≥ 0.75

**Waste estimate:** Template string sums parsed `duration` metadata across affected steps when
available; otherwise a non-numeric fallback. LLM may refine to per week/month in `thorough` mode.

**Evidence:** Reuses generalized `find_evidence(..., finding_kind="redundancy")`. Up to two
quotes per finding (one per affected step). Quotes are never invented.

**Citations:** Each evidence item is promoted to `JobOutput.citations[]` with
`finding_id=rd-...`, `node_id` from the affected step, and `trust_level="untrusted"`.

**LLM enrichment (`thorough` mode only):** Refines `description` and `waste_estimate`; may
omit false positives. Ungrounded LLM quotes are dropped post-validation.

**Pairwise cap:** Graphs with more than 500 analyzable nodes skip pairwise redundancy rules and
emit an analyzer warning.

**Partial analysis output:** `analysis.bottlenecks` and `analysis.redundancies` are populated
independently; empty sections are omitted from serialized output.

**Standalone debug CLI:** `python -m ai_workflow_mapper.cli.analyze_bottlenecks --redundancies --pretty flowchart.mmd`

### Automation Opportunity Scorer

After `ProcessGraphBuilder`, when `process_graph` is non-empty, the processor runs
`AutomationAnalyzer` (`workflow/automation_analyzer.py`) using per-step heuristics
(`workflow/automation_heuristics.py`) and document quote matching
(`workflow/evidence_matcher.py`).

**Activation:** Same gate as other analyzers. No new `job_options` flag; `mode` controls
LLM depth only.

**Detection (deterministic):** One merged opportunity per task/decision node (`id=ao-{node_id}`):

- **Rule-based:** `type=task` with validation/calculation verbs and no judgment keywords
- **Data entry:** data-transfer verbs or tool-associated manual entry
- **Repetitive approval:** approval/review keywords plus routine/low-judgment proxy keywords
  (true >95% grant rate not available from graph alone)
- **Scheduled recurring:** `frequency` metadata or schedule keywords in label
- **Notification/status:** notify/email/alert/confirmation keywords

Steps whose labels indicate existing automation (`automated`, `API`, `integration`, …) are
skipped.

**Ranking:** Opportunities are sorted by `estimated_weekly_minutes / effort_weight` and assigned
`priority` (`"1"`, `"2"`, …) with narrative `roi` strings. `effort` is `Low`/`Medium`/`High`
per schema enum casing.

**Evidence:** `find_evidence(..., finding_kind="automation")` with `ao-{node_id}` warnings.
Quotes are never invented.

**Citations:** `finding_id=ao-{node_id}`, `node_id`, `trust_level="untrusted"`.

**Empty result:** When no opportunities survive heuristics (and LLM filtering in thorough mode),
omit `automation_opportunities` and append job warning:
`No high-confidence automation opportunities found.`

**LLM enrichment (`thorough` mode only):** Refines `suggested_approach`, `time_savings_per_week`,
`roi`, and `effort`; may omit false positives. Ungrounded LLM quotes are dropped.

**Standalone debug CLI:**
`python -m ai_workflow_mapper.cli.analyze_bottlenecks --automation --pretty flowchart.mmd`

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
