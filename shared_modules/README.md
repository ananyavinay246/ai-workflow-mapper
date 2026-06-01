# Shared Module Contracts For AI Workflow Mapper

This folder contains only the shared module contracts applicable to AI Workflow Mapper.

Interns are expected to build project-local implementations for these modules first. The local implementations must conform to these contracts so they can be exchanged for shared implementations later.

## Applicable Modules

| Module | Responsibility | Notes |
|---|---|---|
| [document_loader](document_loader/contract.md) | Convert supported files into normalized text, metadata, and extracted structured elements. | Parser quirks stay inside this module. |
| [llm_adapter](llm_adapter/contract.md) | Route model calls, enforce structured output, retries, timeouts, cost limits, and provider fallback. | Product code should not call OpenAI, Anthropic, or other providers directly. |
| [report_renderer](report_renderer/contract.md) | Render validated structured data into Markdown, HTML, DOCX, PDF, or other outputs. | Rendering should not own domain analysis. |
| [evaluation_harness](evaluation_harness/contract.md) | Load fixtures, run scenarios, validate outputs, score rubrics, and emit eval reports. | Should be repeatable in CI. |

## Standard Files In Each Module

- contract.md: human-readable module boundary.
- schemas/input.schema.json: request envelope for calling the module.
- schemas/output.schema.json: successful response envelope.
- schemas/config.schema.json: allowed configuration shape.
- schemas/error.schema.json: module error envelope and reason codes.
- examples/request.example.json: minimal synthetic request.
- examples/response.example.json: minimal synthetic response.
- tests/contract_tests.md: tests every local or shared implementation should pass.
