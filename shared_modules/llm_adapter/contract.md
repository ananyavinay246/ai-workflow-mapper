# LLM Adapter Contract

## Module Id

llm_adapter

## Purpose

Route model calls, enforce structured output, retries, timeouts, cost limits, and provider fallback.

## Public Operations

- complete
- complete_structured
- repair_structured_output
- estimate_cost

## Inputs

Prompt messages, model constraints, structured-output schema, safety context, timeout, retry policy, and cost budget.

## Outputs

Model response, validated structured object when requested, token/cost metadata, provider/model provenance, warnings, and refusal/safety signals.

## Error Codes

- llm_provider_unavailable
- llm_timeout
- llm_schema_validation_failed
- llm_cost_limit_exceeded
- llm_safety_blocked

## Configuration

Approved providers/models, fallback order, timeout, retry policy, budget limits, and structured-output repair policy.

## Required Behaviors

- Validate structured outputs before returning them to product logic
- Surface provider/model provenance for observability
- Enforce cost and latency budgets
- Keep provider SDK objects out of product code

## Security And Privacy Rules

- Do not log prompts or completions unless the project explicitly allows redacted logging
- Keep API keys in secret storage
- Apply prompt-injection and data-boundary controls defined by the project

## Non-Goals

- Owning domain prompts
- Deciding final business action
- Persisting conversation history unless explicitly requested

## Project-Local Implementation

Interns are expected to implement this module as a project-local adapter first when their project depends on it. The local implementation must keep vendor/library details behind this contract and must pass the contract tests in tests/contract_tests.md.

Recommended local paths:

- Interface or protocol: platform/contracts/llm_adapter
- Project-local implementation: platform/local/llm_adapter
- Contract tests: tests/contracts/llm_adapter

## Shared Replacement Criteria

- The shared implementation passes this module's contract tests.
- The project-specific acceptance gate still passes.
- Product-code call sites do not change.
- Security, privacy, logging, and audit behavior are equivalent or better.
- The technical lead approves swaps in sensitive domains.
