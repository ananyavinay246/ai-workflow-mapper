# AI Workflow Mapper Deployment Notes

## Baseline Target

- Runtime: Python 3.12+ for Vercel deployment. Vercel currently supports Python 3.12 as the default plus newer supported Python versions; declare the chosen version in `pyproject.toml`, `.python-version`, or another Vercel-recognized project file.
- Deployment environment: Vercel for hosted app/API surfaces and scheduled/serverless jobs where applicable.
- Service: FastAPI or equivalent ASGI/WSGI HTTP app compatible with Vercel's Python runtime. The deployed app should expose a top-level `app` object from a Vercel-recognized entrypoint such as `app.py`, `main.py`, `server.py`, `index.py`, `asgi.py`, or `wsgi.py`.
- Workers: only when needed; use Vercel scheduled/serverless jobs where appropriate, and document any non-Vercel worker or queue runtime in IMPLEMENTATION_NOTES.md.
- Storage: Supabase Postgres for deployed persistent data; local development may use SQLite/filesystem fixtures. Prefer Supabase Storage for deployed object/file artifacts when the project needs object storage.
- Secrets: managed environment variables or secret store in the deployment environment.
- Dependency setup: `pyproject.toml` is the canonical Python project file. `requirements.txt` may be used as an optional bridge or exported lock file.

## Async Job Processing On Vercel

The standard `/jobs` API can run on Vercel without a traditional long-running worker process.

Recommended baseline:

1. `POST /jobs` runs as a Vercel Function, validates input, inserts a job row in Supabase Postgres, and returns `202 Accepted`.
2. A bounded processor claims accepted jobs from Supabase, sets status to `running`, executes one job or a small batch, and writes the final status/result/artifacts.
3. `GET /jobs/{job_id}` reads job state from Supabase and returns the schema-valid output envelope.

Implementation options:

- Local development: a Python CLI command or local process can claim and run pending jobs.
- Simple deployed projects: a protected Vercel Function or Vercel Cron Job can poll Supabase for accepted jobs and process a bounded batch. Cron-triggered processors should be configured in `vercel.json`, invoke an API route, and verify a shared secret such as `CRON_SECRET`.
- Higher reliability projects: consider Vercel Queues or Vercel Workflow only when simple Supabase polling is not enough and the technical lead approves the added complexity. Vercel Workflow is available in beta on all plans with included usage allotments and usage-based billing beyond those allotments; it is TypeScript-first, so keep Python as the default backend path unless an exception is approved.

Design constraints:

- Keep each function invocation within the configured Vercel max duration. Use `maxDuration` in `vercel.json` when needed, for example `"maxDuration": 300`. Current Vercel Function limits with Fluid Compute list 300 seconds for Hobby and up to 800 seconds for Pro/Enterprise, but interns should use the lowest value their job realistically needs and treat long work as a reason to split the job.
- Keep Python function bundles under Vercel's Python function size limit of 500 MB uncompressed. Python deployments do not get automatic tree-shaking, so keep runtime dependencies lean and use `excludeFiles` in `vercel.json` for tests, fixtures, sample data, and static assets that should not ship in the function bundle.
- Keep request and response payloads small. Vercel Functions have a 4.5 MB request/response body limit; large uploads, crawled content, generated reports, and exported files should go through Supabase Storage or another approved artifact store.
- Store large files and generated artifacts in Supabase Storage instead of returning them directly in the HTTP response.
- Make processors idempotent because retries can happen after timeouts or partial failures.
- Record the chosen processing approach in `IMPLEMENTATION_NOTES.md`.

## Required Environment Variables

See ops/env.example. Treat it as a configuration checklist, not a complete deployment template. Remove unused variables, add project-specific integration keys, and do not add Vercel or Supabase platform config templates unless the implementation requires one and the technical lead approves it.

## Release Requirements

- Acceptance gate passes.
- Database migrations are applied and reversible.
- Health endpoint responds successfully.
- Logs contain trace ids and no secrets.
- Rollback steps are documented in ops/runbook.md.
