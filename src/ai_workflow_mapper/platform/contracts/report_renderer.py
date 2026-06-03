from enum import Enum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ReportRendererOperation(str, Enum):
    render_report = "render_report"
    export_artifact = "export_artifact"
    validate_template = "validate_template"


class ReportRendererErrorCode(str, Enum):
    template_not_found = "template_not_found"
    render_failed = "render_failed"
    format_unsupported = "format_unsupported"
    artifact_write_failed = "artifact_write_failed"


class ReportRendererStatus(str, Enum):
    succeeded = "succeeded"
    denied = "denied"
    failed = "failed"
    needs_review = "needs_review"


class ReportRendererContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    actor_id: str
    tenant_id: str
    environment: str


class ReportRendererRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    module_id: Literal["report_renderer"] = "report_renderer"
    operation: ReportRendererOperation
    input: dict[str, Any]
    context: ReportRendererContext
    trace_id: str = Field(min_length=1)


class ReportRendererResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: Literal["report_renderer"] = "report_renderer"
    operation: ReportRendererOperation
    status: ReportRendererStatus
    result: dict[str, Any]
    warnings: list[str]
    metadata: dict[str, Any]
    trace_id: str = Field(min_length=1)


class ReportRendererError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: Literal["report_renderer"] = "report_renderer"
    operation: ReportRendererOperation
    error_code: ReportRendererErrorCode
    message: str
    retryable: bool
    trace_id: str
    details: dict[str, Any] | None = None


class ReportRendererConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: Literal["report_renderer"] = "report_renderer"
    environment: Literal["local", "staging", "production"]
    implementation: str
    settings: dict[str, Any]
    security: dict[str, Any]
    observability: dict[str, Any] | None = None


class ReportRendererProtocol(Protocol):
    def handle(self, request: ReportRendererRequest) -> ReportRendererResponse: ...
    def get_config(self) -> ReportRendererConfig: ...
