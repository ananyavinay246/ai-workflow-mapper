# AI Workflow Mapper Schemas

JSON Schema (draft 2020-12) contracts for the public API, domain payloads, and shared validation with tests and fixtures.

## Envelope schemas

- `input.schema.json` — `POST /jobs` request (`$ref` → workflow input + job options).
- `output.schema.json` — job status response (`$ref` → workflow result, citations, diagram artifacts).
- `config.schema.json` — deployment/runtime configuration (not per-request).
- `errors.schema.json` — API error body.
- `audit_log.schema.json` — audit event shape.

## Domain schemas

- `workflow_input.schema.json` — `input` payload: documents + optional description.
- `job_options.schema.json` — `options` payload: output format, mode, diagram settings, cost/review flags.
- `workflow_result.schema.json` — `result` on success: `normalization_summary` (required), optional `process_graph` and `analysis`.
- `job_error_result.schema.json` — `result` when `status` is `failed` (`error` string).
- `process_extraction.schema.json` — LLM structured output before graph build (`llm_adapter.complete_structured`).
- `process_graph.schema.json` — canonical nodes, edges, actors, swimlanes.
- `analysis_findings.schema.json` — report sections (aligned with `report.md.j2`).
- `citation.schema.json` — evidence items on job output.
- `diagram_artifact.schema.json` — generated file references in `artifacts[]`.

## Pydantic mirrors

| Schema | Python model |
|--------|----------------|
| `workflow_input` | `workflow.domain.WorkflowInput`, `InputDocument` |
| `job_options` | `workflow.domain.JobOptions` |
| `workflow_result` | `workflow.domain.WorkflowResult`, `NormalizationSummary` |
| Envelope | `api.models.JobInput`, `JobOutput`, `Citation`, `JobArtifact` |

API validation uses Pydantic on `JobInput` / `JobOutput`. Contract tests use `jsonschema` with a shared `$id` store (see `tests/schemas/test_contract_schemas.py`).

## Examples

- `examples/request.example.json` — validates against `input.schema.json`.
- `examples/response.example.json` — validates against `output.schema.json`.

When adding fields, update the JSON Schema first, then Pydantic models, then examples and `IMPLEMENTATION_NOTES.md` if the change is contract-affecting.
