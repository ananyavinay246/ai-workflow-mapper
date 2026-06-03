from enum import Enum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class DocumentLoaderOperation(str, Enum):
    detect_file_type = "detect_file_type"
    load_document = "load_document"
    extract_text = "extract_text"
    extract_metadata = "extract_metadata"


class DocumentLoaderErrorCode(str, Enum):
    document_unsupported_type = "document_unsupported_type"
    document_too_large = "document_too_large"
    document_parse_failed = "document_parse_failed"
    document_password_required = "document_password_required"


class DocumentLoaderStatus(str, Enum):
    succeeded = "succeeded"
    denied = "denied"
    failed = "failed"
    needs_review = "needs_review"


class DocumentLoaderContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    actor_id: str
    tenant_id: str
    environment: str


class DocumentLoaderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    module_id: Literal["document_loader"] = "document_loader"
    operation: DocumentLoaderOperation
    input: dict[str, Any]
    context: DocumentLoaderContext
    trace_id: str = Field(min_length=1)


class DocumentLoaderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: Literal["document_loader"] = "document_loader"
    operation: DocumentLoaderOperation
    status: DocumentLoaderStatus
    result: dict[str, Any]
    warnings: list[str]
    metadata: dict[str, Any]
    trace_id: str = Field(min_length=1)


class DocumentLoaderError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: Literal["document_loader"] = "document_loader"
    operation: DocumentLoaderOperation
    error_code: DocumentLoaderErrorCode
    message: str
    retryable: bool
    trace_id: str
    details: dict[str, Any] | None = None


class DocumentLoaderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: Literal["document_loader"] = "document_loader"
    environment: Literal["local", "staging", "production"]
    implementation: str
    settings: dict[str, Any]
    security: dict[str, Any]
    observability: dict[str, Any] | None = None


class DocumentLoaderProtocol(Protocol):
    def handle(self, request: DocumentLoaderRequest) -> DocumentLoaderResponse: ...
    def get_config(self) -> DocumentLoaderConfig: ...
