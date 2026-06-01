# AI Workflow Mapper Runbook

## Health Check

- Verify /health for API deployments.
- Verify the job processor path is healthy if async jobs are used, such as a local processor command, protected Vercel Function, Cron-triggered processor, or queue-backed consumer.

## Common Incidents

### Invalid Input Spike
- Check recent validation errors.
- Confirm callers are using schemas/input.schema.json.

### LLM Provider Failure
- Check provider status and API key configuration.
- Confirm retry and fallback behavior.
- Disable non-critical LLM features if the system supports degraded mode.

### Evaluation Regression
- Re-run the evaluation command from `eval/run_eval.md`, usually `python -m ai_workflow_mapper.eval.run_eval --fixtures fixtures/golden --rubric eval/rubric.md`.
- Compare changed prompts, schemas, and fixtures.
- Record the finding in IMPLEMENTATION_NOTES.md.

### Job Stuck In Accepted Or Running
- Check Supabase job rows for stale `accepted` or `running` statuses.
- Confirm the processor can claim one job and update status transitions.
- Check Vercel Function, Cron, or queue logs for timeout, rate-limit, or provider errors.
- Retry only with the original `request_id` or a documented operator action.

### Sensitive Data Concern
- Stop affected jobs.
- Preserve audit logs.
- Rotate exposed credentials if any.
- Notify the technical lead or production owner.
