from enum import Enum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class LLMAdapterOperation(str, Enum):
    complete = "complete"
    complete_structured = "complete_structured"
    repair_structured_output = "repair_structured_output"
    estimate_cost = "estimate_cost"


class LLMAdapterErrorCode(str, Enum):
    llm_provider_unavailable = "llm_provider_unavailable"
    llm_timeout = "llm_timeout"
    llm_schema_validation_failed = "llm_schema_validation_failed"
    llm_cost_limit_exceeded = "llm_cost_limit_exceeded"
    llm_safety_blocked = "llm_safety_blocked"


class LLMAdapterStatus(str, Enum):
    succeeded = "succeeded"
    denied = "denied"
    failed = "failed"
    needs_review = "needs_review"


class LLMAdapterContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    actor_id: str
    tenant_id: str
    environment: str


class LLMAdapterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    module_id: Literal["llm_adapter"] = "llm_adapter"
    operation: LLMAdapterOperation
    input: dict[str, Any]
    context: LLMAdapterContext
    trace_id: str = Field(min_length=1)


class LLMAdapterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: Literal["llm_adapter"] = "llm_adapter"
    operation: LLMAdapterOperation
    status: LLMAdapterStatus
    result: dict[str, Any]
    warnings: list[str]
    metadata: dict[str, Any]
    trace_id: str = Field(min_length=1)


class LLMAdapterError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: Literal["llm_adapter"] = "llm_adapter"
    operation: LLMAdapterOperation
    error_code: LLMAdapterErrorCode
    message: str
    retryable: bool
    trace_id: str
    details: dict[str, Any] | None = None


class LLMAdapterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: Literal["llm_adapter"] = "llm_adapter"
    environment: Literal["local", "staging", "production"]
    implementation: str
    settings: dict[str, Any]
    security: dict[str, Any]
    observability: dict[str, Any] | None = None


class LLMAdapterProtocol(Protocol):
    def handle(self, request: LLMAdapterRequest) -> LLMAdapterResponse: ...
    def get_config(self) -> LLMAdapterConfig: ...
