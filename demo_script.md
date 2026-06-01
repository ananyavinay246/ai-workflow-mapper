# AI Workflow Mapper Demo Script

Use this script to prepare technical lead review evidence. Update command names after implementation, but keep the same proof points.

## Demo Goal

Show that AI Workflow Mapper can accept a realistic input, validate it, run the core workflow, produce a structured result, and explain how the result is verified.

## Required Flow

1. Show the relevant input fixture from fixtures/simple or fixtures/golden.
2. Run the implementation using the CLI or API.
3. Show the validated output from examples/response.example.json or the generated artifact.
4. Show citations, warnings, or human-review flags when the domain requires them.
5. Run the acceptance command set from acceptance.md.
6. Open ops/runbook.md and explain how a production operator would diagnose a failed job.
