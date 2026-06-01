# Report Renderer Contract

## Module Id

report_renderer

## Purpose

Render validated structured data into Markdown, HTML, DOCX, PDF, or other outputs.

## Public Operations

- render_report
- export_artifact
- validate_template

## Inputs

Validated structured data, template id/version, output format, asset references, and rendering options.

## Outputs

Rendered content or artifact reference, format metadata, warnings, and template provenance.

## Error Codes

- template_not_found
- render_failed
- format_unsupported
- artifact_write_failed

## Configuration

Template registry, allowed output formats, artifact storage binding, sanitization policy, and rendering timeout.

## Required Behaviors

- Render only from validated structured data
- Keep template/version provenance in outputs
- Sanitize HTML or rich output where relevant
- Return artifact metadata instead of leaking storage internals

## Security And Privacy Rules

- Do not execute template-supplied code
- Redact secrets and sensitive fields marked non-renderable
- Avoid writing artifacts outside approved storage

## Non-Goals

- Performing domain analysis
- Fetching source data
- Approving generated content

## Project-Local Implementation

Interns are expected to implement this module as a project-local adapter first when their project depends on it. The local implementation must keep vendor/library details behind this contract and must pass the contract tests in tests/contract_tests.md.

Recommended local paths:

- Interface or protocol: platform/contracts/report_renderer
- Project-local implementation: platform/local/report_renderer
- Contract tests: tests/contracts/report_renderer

## Shared Replacement Criteria

- The shared implementation passes this module's contract tests.
- The project-specific acceptance gate still passes.
- Product-code call sites do not change.
- Security, privacy, logging, and audit behavior are equivalent or better.
- The technical lead approves swaps in sensitive domains.
