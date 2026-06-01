# Evaluation Harness Contract

## Module Id

evaluation_harness

## Purpose

Load fixtures, run scenarios, validate outputs, score rubrics, and emit eval reports.

## Public Operations

- load_cases
- run_eval
- score_results
- emit_report

## Inputs

Fixture directory, golden answer file, tool runner command/API binding, rubric, thresholds, and run metadata.

## Outputs

Case results, aggregate scores, schema validation results, failure details, and evaluation report artifact.

## Error Codes

- eval_fixture_invalid
- eval_runner_failed
- eval_threshold_failed
- eval_report_write_failed

## Configuration

Fixture paths, scoring rubric, pass thresholds, timeout, parallelism, and artifact output path.

## Required Behaviors

- Exit non-zero when thresholds fail
- Validate outputs against schemas before scoring
- Keep evaluation runs reproducible
- Separate case failure from runner failure

## Security And Privacy Rules

- Use synthetic or approved redacted fixtures
- Do not send adversarial fixtures to unapproved systems
- Avoid logging secrets from tool runtime

## Non-Goals

- Replacing unit tests
- Defining product requirements by itself
- Approving production release without technical lead review

## Project-Local Implementation

Interns are expected to implement this module as a project-local adapter first when their project depends on it. The local implementation must keep vendor/library details behind this contract and must pass the contract tests in tests/contract_tests.md.

Recommended local paths:

- Interface or protocol: platform/contracts/evaluation_harness
- Project-local implementation: platform/local/evaluation_harness
- Contract tests: tests/contracts/evaluation_harness

## Shared Replacement Criteria

- The shared implementation passes this module's contract tests.
- The project-specific acceptance gate still passes.
- Product-code call sites do not change.
- Security, privacy, logging, and audit behavior are equivalent or better.
- The technical lead approves swaps in sensitive domains.
