"""Domain Pydantic models for the JobInput.input dict.

These are internal — not part of any JSON schema contract.
schemas/input.schema.json uses additionalProperties: true; these models
narrow that shape for the workflow pipeline.
"""

from pydantic import BaseModel, ConfigDict, Field


class InputDocument(BaseModel):
    filename: str = Field(min_length=1)
    content_b64: str = Field(min_length=1)  # base64-encoded file bytes
    source_type: str = "document"           # "interview", "sop", "diagram", "tool_export"


class WorkflowInput(BaseModel):
    # extra="ignore" — forward-compatible; callers may pass unknown fields
    model_config = ConfigDict(extra="ignore")

    documents: list[InputDocument] = []
    description: str | None = None
