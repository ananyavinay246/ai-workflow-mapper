# AI Workflow Mapper

This is the starter workspace for the AI Workflow Mapper build. Treat the included specification documents as the source of truth, then expand this README as implementation decisions, setup steps, commands, and deployment notes become real.

## Start Here

- Read `specification_ai_workflow_mapper.md` for the full product specification.
- Read `acceptance.md` to understand the production acceptance gate.
- Read `AGENT_GUIDE.md` before working with coding agents.
- Read `shared_modules/` for the shared module contracts this project must follow.

## Project Status

- Intern owner(s):
- Current phase: specification package
- Last updated:
- Demo command:
- Test command:
- Eval command:

## Local Commands

Use cross-platform Python commands so the project works on Windows and macOS without requiring Bash, GNU Make, or Docker. Update these commands if the implementation uses a different package layout.

- Install: `python -m pip install -e ".[dev]"`
- Run API locally: `python -m ai_workflow_mapper.api` or the project-documented equivalent.
- Test: `python -m pytest`
- Security: `python -m pytest tests/security` or the project-documented equivalent.
- Eval: `python -m ai_workflow_mapper.eval.run_eval --fixtures fixtures/golden --rubric eval/rubric.md`
- Lint: `python -m ruff check .` or the project-documented equivalent.

## Python Project Setup

The install command above assumes the implementation will create `pyproject.toml`. Many interns may know `requirements.txt`; `pyproject.toml` is the modern Python project file that can hold package metadata, runtime dependencies, dev dependencies, and tool config in one place.

Start with a small version like this when implementation begins:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "ai-workflow-mapper"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi",
  "pydantic",
  "httpx",
]

[project.optional-dependencies]
dev = [
  "pytest",
  "ruff",
  "jsonschema",
]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
```

What this means:

- `[project]` describes the installable Python app.
- `dependencies` are packages needed by the app at runtime.
- `[project.optional-dependencies].dev` is what `python -m pip install -e ".[dev]"` installs for tests, linting, and local development.
- `[tool.pytest...]` and `[tool.ruff]` keep tool configuration with the project.
- `requirements.txt` is acceptable as a temporary bridge or exported lock file, but the production-ready project should document the canonical setup in `pyproject.toml`.

## Standard Job Flow

The API contract is intentionally job-based:

1. `POST /jobs` validates input, creates a durable job record, and returns `202 Accepted` with `status: accepted`.
2. A processor claims the job, marks it `running`, executes the workflow, stores artifacts, and ends with `succeeded`, `failed`, or `needs_review`.
3. `GET /jobs/{job_id}` returns the current status and final result when available.

For implementation, keep the HTTP route code separate from the domain workflow. The route owns validation, idempotency, status transitions, persistence, and audit logging. The workflow should be callable from a Python function such as `run_job(input, options, context)`.

This does not require Redis, Celery, Docker, or a separate server. A first deployed version can store jobs in Supabase Postgres and process accepted jobs with a bounded Vercel Function or Cron-triggered processor. Vercel Queues, Vercel Workflow, or an approved external queue should be treated as advanced options for stronger delivery guarantees or higher throughput, and should be used only with technical lead approval. Workflow is TypeScript-first and beta, while this package's backend path is Python-first by default.

## Key Files

- `specification_ai_workflow_mapper.md`: full project specification and source of truth.
- `pyproject.toml`: expected Python project setup file once implementation begins.
- `openapi.yaml`: required public API surface.
- `schemas/`: JSON schemas for inputs, outputs, errors, config, and audit logs.
- `fixtures/`: simple, golden, and adversarial cases for testing and evaluation.
- `eval/`: evaluation rubric, golden answers, and run instructions.
- `ops/`: environment example, deployment notes, and production runbook.
- `examples/`: example requests and reports.
- `IMPLEMENTATION_NOTES.md`: implementation decisions and contract-affecting notes.
- `CHANGELOG.md`: project-level change history.
- `AGENT_GUIDE.md`: recommended agent practices and starter prompts.
- `shared_modules/`: filtered shared module contracts for this project.

## Applicable Shared Modules

- shared_modules/document_loader/
- shared_modules/llm_adapter/
- shared_modules/report_renderer/
- shared_modules/evaluation_harness/

## Notes For Future Maintainers

- Keep public schemas, API examples, and acceptance criteria aligned as implementation changes.
- Record contract-affecting decisions in `IMPLEMENTATION_NOTES.md`.
- Add real setup and operating commands to this README as soon as they exist.
