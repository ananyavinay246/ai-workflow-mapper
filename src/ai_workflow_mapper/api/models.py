"""Pydantic models matching schemas/input.schema.json, output.schema.json, errors.schema.json."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class JobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    tool_id: Literal["ai_workflow_mapper"] = "ai_workflow_mapper"
    input: dict[str, Any]
    options: dict[str, Any]
    metadata: dict[str, Any] | None = None


class JobArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    type: str
    description: str | None = None


class JobOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    tool_id: Literal["ai_workflow_mapper"] = "ai_workflow_mapper"
    status: Literal["accepted", "running", "succeeded", "failed", "needs_review"]
    result: dict[str, Any] | None
    citations: list[dict[str, Any]] | None = None
    warnings: list[str] | None = None
    artifacts: list[JobArtifact] | None = None
    metadata: dict[str, Any]


class ApiError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_code: str
    message: str
    retryable: bool
    trace_id: str
    details: dict[str, Any] | None = None
