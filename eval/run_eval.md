# AI Workflow Mapper Evaluation Runner

The implementation must provide a repeatable evaluation command before release.

Recommended command:

```bash
python -m ai_workflow_mapper.eval.run_eval --fixtures fixtures/golden --rubric eval/rubric.md
```

If the implementation uses a different Python package layout, document the exact `python -m ...` command in the root `README.md` and `acceptance.md`. A Makefile may wrap this command later, but it should not be the only supported way to run evaluation.

Expected behavior:

1. Load cases from `fixtures/golden`.
2. Run the tool against each case.
3. Validate outputs against `schemas/output.schema.json`.
4. Score each case with `eval/rubric.md`.
5. Exit non-zero if the acceptance threshold is not met.
