# AI Workflow Mapper Acceptance Gate

This file defines the production-readiness gate for AI Workflow Mapper. The main specification remains the narrative source of truth; this file is the pass/fail checklist.

This project should expose cross-platform Python commands that work on Windows and macOS without requiring Bash, GNU Make, or Docker. If the implementation uses a different package layout than the commands below assume, document the exact equivalent commands in `README.md` before final technical lead review.

Makefiles and Docker containers are optional local convenience tools for interns who want to explore ahead. They should wrap or document the Python commands rather than replace them. The deployment target is Vercel serverless/app hosting, so Docker is not required for production deployment.

## Required Checks

- Static checks pass with `python -m ruff check .` or the project-equivalent command.
- Unit and integration tests pass with `python -m pytest`.
- Security checks pass with `python -m pytest tests/security` or a documented equivalent.
- Evaluation passes with `python -m ai_workflow_mapper.eval.run_eval --fixtures fixtures/golden --rubric eval/rubric.md` or a documented equivalent against `fixtures/golden`.
- Python project setup is documented in `pyproject.toml`; `requirements.txt` may exist as an optional bridge or exported lock file.
- The demo in `demo_script.md` runs from a clean checkout.
- All public inputs and outputs validate against `schemas/`.
- API behavior matches `openapi.yaml` if the service exposes HTTP endpoints.
- Sensitive data listed in the Production Build Contract is not logged, leaked, or stored outside approved locations.

## Human Review Gates

- High-impact recommendations require human approval before action.
- Any generated legal, HR, compliance, sales, or policy output must clearly identify its evidence and limitations.
- Deviations from this gate must be written in `IMPLEMENTATION_NOTES.md` and approved by the technical lead.
