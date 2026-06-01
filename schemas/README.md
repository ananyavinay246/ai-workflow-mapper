# AI Workflow Mapper Schemas

These JSON Schema files are starter source-of-truth contracts. They define the public request, response, config, error, and audit-log shapes that OpenAPI, fixtures, evals, tests, and future clients can all reference.

Because implementation is Python-based, use Pydantic `BaseModel` classes for day-to-day runtime validation and developer ergonomics. The recommended pattern is:

1. Treat these JSON Schema files as the public contract artifacts.
2. Implement matching Pydantic models in the Python app.
3. Validate incoming API/CLI data with the Pydantic models before side effects.
4. Keep exported Pydantic JSON Schema aligned with the checked-in `*.schema.json` files.

## Files

- `input.schema.json`: accepted request format.
- `output.schema.json`: returned job/result format.
- `config.schema.json`: runtime configuration shape.
- `errors.schema.json`: error response shape.
- `audit_log.schema.json`: audit event shape.

## Example Pydantic Adaptation

```python
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

class AiWorkflowMapperJobInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(..., min_length=1)
    tool_id: Literal["ai_workflow_mapper"]
    args: dict[str, Any] = Field(..., alias="input")
    options: dict[str, Any]
    metadata: dict[str, Any] | None = None

class AiWorkflowMapperJobOutput(BaseModel):
    job_id: str = Field(..., min_length=1)
    tool_id: Literal["ai_workflow_mapper"]
    status: Literal["accepted", "running", "succeeded", "failed", "needs_review"]
    result: dict[str, Any] | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

The public JSON field is still `input`. The Python attribute is named `args` with `alias="input"` to avoid shadowing Python's built-in `input()`. When exporting data that must match the public contract, use Pydantic's alias-aware serialization, such as `model_dump(by_alias=True)`.

Before implementation acceptance, narrow the generic `args/input` and `result` dictionaries into domain-specific Pydantic models and update the JSON Schema files to match.
