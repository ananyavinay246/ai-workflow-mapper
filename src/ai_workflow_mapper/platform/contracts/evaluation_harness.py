from enum import Enum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class EvaluationHarnessOperation(str, Enum):
    load_cases = "load_cases"
    run_eval = "run_eval"
    score_results = "score_results"
    emit_report = "emit_report"


class EvaluationHarnessErrorCode(str, Enum):
    eval_fixture_invalid = "eval_fixture_invalid"
    eval_runner_failed = "eval_runner_failed"
    eval_threshold_failed = "eval_threshold_failed"
    eval_report_write_failed = "eval_report_write_failed"


class EvaluationHarnessStatus(str, Enum):
    succeeded = "succeeded"
    denied = "denied"
    failed = "failed"
    needs_review = "needs_review"


class EvaluationHarnessContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    actor_id: str
    tenant_id: str
    environment: str


class EvaluationHarnessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    module_id: Literal["evaluation_harness"] = "evaluation_harness"
    operation: EvaluationHarnessOperation
    input: dict[str, Any]
    context: EvaluationHarnessContext
    trace_id: str = Field(min_length=1)


class EvaluationHarnessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: Literal["evaluation_harness"] = "evaluation_harness"
    operation: EvaluationHarnessOperation
    status: EvaluationHarnessStatus
    result: dict[str, Any]
    warnings: list[str]
    metadata: dict[str, Any]
    trace_id: str = Field(min_length=1)


class EvaluationHarnessError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: Literal["evaluation_harness"] = "evaluation_harness"
    operation: EvaluationHarnessOperation
    error_code: EvaluationHarnessErrorCode
    message: str
    retryable: bool
    trace_id: str
    details: dict[str, Any] | None = None


class EvaluationHarnessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: Literal["evaluation_harness"] = "evaluation_harness"
    environment: Literal["local", "staging", "production"]
    implementation: str
    settings: dict[str, Any]
    security: dict[str, Any]
    observability: dict[str, Any] | None = None


class EvaluationHarnessProtocol(Protocol):
    def handle(self, request: EvaluationHarnessRequest) -> EvaluationHarnessResponse: ...
    def get_config(self) -> EvaluationHarnessConfig: ...
