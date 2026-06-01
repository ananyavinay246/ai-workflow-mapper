# Report Renderer Contract Tests

Every project-local or shared implementation of report_renderer should include contract tests for these behaviors.

## Required Cases

- Happy path for each public operation:
- render_report
- export_artifact
- validate_template
- Invalid input validates against schemas/input.schema.json and returns a structured error.
- Dependency or provider failure returns schemas/error.schema.json.
- Sensitive values are redacted from logs, errors, metadata, and audit events.
- Output validates against schemas/output.schema.json.
- Configuration validates against schemas/config.schema.json.
- Timeout and retry behavior matches the project configuration when relevant.
- Backward-compatible fields remain stable across implementation swaps.

## Swap Test

Run the same contract test suite against the project-local implementation and the candidate shared implementation. A swap is acceptable only if both pass and the project acceptance gate still passes.
