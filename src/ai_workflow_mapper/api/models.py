"""Pydantic models matching schemas/input.schema.json, output.schema.json, errors.schema.json."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_workflow_mapper.workflow.domain import JobOptions, WorkflowInput


class JobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    tool_id: Literal["ai_workflow_mapper"] = "ai_workflow_mapper"
    input: WorkflowInput
    options: JobOptions = Field(default_factory=JobOptions)
    metadata: dict[str, Any] | None = None


class JobArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    type: str
    description: str | None = None
    format: str | None = None
    diagram_type: str | None = None
    mime_type: str | None = None
    storage_uri: str | None = None
    content: str | None = None
    checksum: str | None = None


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_filename: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    trust_level: Literal["untrusted", "internal", "verified"] = "untrusted"
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    node_id: str | None = None
    finding_id: str | None = None


class JobOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    tool_id: Literal["ai_workflow_mapper"] = "ai_workflow_mapper"
    status: Literal["accepted", "running", "succeeded", "failed", "needs_review"]
    result: dict[str, Any] | None
    citations: list[Citation] | None = None
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
