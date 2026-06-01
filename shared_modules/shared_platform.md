# Shared Production Platform For AI Workflow Mapper

This is the project-specific shared platform subset for AI Workflow Mapper. It intentionally mentions only the shared modules this project depends on.

## Core Rule

Projects are expected to implement project-local versions of their required shared platform modules first. Product logic must depend on the module contract rather than directly depending on vendor SDKs, Supabase clients, storage clients, model providers, or one-off helpers.

The default plan is project-local first. Use an existing shared implementation at project start only when the technical lead explicitly assigns that path.

## Applicable Shared Modules

| Module id | Black-box responsibility | Notes |
|---|---|---|
| document_loader | Convert supported files into normalized text, metadata, and extracted structured elements. | Parser quirks stay inside this module. |
| llm_adapter | Route model calls, enforce structured output, retries, timeouts, cost limits, and provider fallback. | Product code should not call OpenAI, Anthropic, or other providers directly. |
| report_renderer | Render validated structured data into Markdown, HTML, DOCX, PDF, or other outputs. | Rendering should not own domain analysis. |
| evaluation_harness | Load fixtures, run scenarios, validate outputs, score rubrics, and emit eval reports. | Should be repeatable in CI. |

## Smaller Contracts For Broad Applicable Modules

| Umbrella | Smaller contracts |
|---|---|
| document_loader | file_type_detector, text_extractor, metadata_extractor, ocr_adapter |
| llm_adapter | model_router, completion_client, structured_output_repair, cost_tracker |
| report_renderer | markdown_renderer, html_renderer, docx_renderer, pdf_renderer |

## Project-Local Implementation Rule

Recommended naming:

- Interface or protocol: platform/contracts/<module_id>
- Project-local implementation: platform/local/<module_id>
- Future shared implementation: platform/shared/<module_id>
- Contract tests: tests/contracts/<module_id>

The important part is the boundary: product code calls the contract, not the implementation.

## Contract Test Expectations

Each project-local implementation should have tests for:

- Happy path behavior.
- Invalid input.
- Provider or dependency failure.
- Sensitive-data redaction.
- Timeout and retry behavior when relevant.
- Deterministic output shape.
- Backward compatibility for public fields.

## Swap Policy

A project-local implementation can be replaced by a shared implementation only when:

- The shared implementation passes the project's existing contract tests.
- The project-specific acceptance gate still passes.
- The implementation notes identify the replacement and any behavior changes.
- The technical lead approves the swap for sensitive domains.
