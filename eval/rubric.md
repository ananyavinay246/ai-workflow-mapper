# AI Workflow Mapper Evaluation Rubric

Use this rubric for the Python evaluation runner, normally `python -m ai_workflow_mapper.eval.run_eval --fixtures fixtures/golden --rubric eval/rubric.md`, or the documented project-equivalent evaluation command.

## Required Dimensions

- Contract validity: outputs validate against schemas/output.schema.json.
- Task success: the result satisfies the domain task described in the main specification.
- Evidence quality: claims cite source data when the domain requires grounding.
- Safety: sensitive data is handled according to the Production Build Contract.
- Reliability: expected errors are returned with schemas/errors.schema.json.
- Operator clarity: logs, artifacts, and warnings make failures diagnosable.

## Scoring

Use a 1-5 score per dimension. A production candidate must average at least 4.0 with no dimension below 3.0 unless the technical lead approves a documented exception.
