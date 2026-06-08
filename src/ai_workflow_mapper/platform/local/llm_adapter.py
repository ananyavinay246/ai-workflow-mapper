import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any

import anthropic
import jsonschema

from ai_workflow_mapper.platform.contracts.llm_adapter import (
    LLMAdapterConfig,
    LLMAdapterError,
    LLMAdapterErrorCode,
    LLMAdapterOperation,
    LLMAdapterRequest,
    LLMAdapterResponse,
    LLMAdapterStatus,
)

_log = logging.getLogger(__name__)

_CONTENT_WRAPPER_OPEN = '<process_content trust_level="untrusted">'
_CONTENT_WRAPPER_CLOSE = "</process_content>"

# Approximate cost per million tokens in USD (claude-sonnet-4-6 pricing)
_COST_PER_M_INPUT_USD = 3.0
_COST_PER_M_OUTPUT_USD = 15.0


def _normalize_json_content(content: str) -> str:
    """Strip optional markdown code fences from model JSON responses."""
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


class LLMAdapterModuleError(Exception):
    def __init__(self, error: LLMAdapterError) -> None:
        self.error = error
        super().__init__(error.message)


class LocalLLMAdapter:
    """Project-local implementation of the llm_adapter contract using Anthropic Claude."""

    MODULE_ID = "llm_adapter"
    DEFAULT_MODEL = "claude-sonnet-4-6"
    DEFAULT_TIMEOUT_S = 180.0
    DEFAULT_MAX_RETRIES = 2
    DEFAULT_COST_LIMIT_USD = 1.0
    DEFAULT_REPAIR_MAX_ATTEMPTS = 2

    def __init__(self, config: LLMAdapterConfig) -> None:
        self._config = config
        api_key = os.environ.get("LLM_API_KEY")
        if not api_key:
            raise RuntimeError("LLM_API_KEY environment variable is not set")
        self._client = anthropic.Anthropic(api_key=api_key)

        s = config.settings
        self._model: str = s.get("model_id", self.DEFAULT_MODEL)
        self._timeout_s: float = float(s.get("timeout_s", self.DEFAULT_TIMEOUT_S))
        self._max_retries: int = int(s.get("max_retries", self.DEFAULT_MAX_RETRIES))
        self._cost_limit_usd: float = float(s.get("cost_limit_usd", self.DEFAULT_COST_LIMIT_USD))
        self._repair_max_attempts: int = int(
            s.get("repair_max_attempts", self.DEFAULT_REPAIR_MAX_ATTEMPTS)
        )

    def handle(self, request: LLMAdapterRequest) -> LLMAdapterResponse:
        t0 = time.monotonic()
        try:
            result, warnings = self._dispatch(request)
            return LLMAdapterResponse(
                module_id=self.MODULE_ID,
                operation=request.operation,
                status=LLMAdapterStatus.succeeded,
                result=result,
                warnings=warnings,
                metadata=self._make_metadata(t0),
                trace_id=request.trace_id,
            )
        except LLMAdapterModuleError as exc:
            return LLMAdapterResponse(
                module_id=self.MODULE_ID,
                operation=request.operation,
                status=LLMAdapterStatus.failed,
                result={"error": exc.error.model_dump(exclude_none=True)},
                warnings=[],
                metadata=self._make_metadata(t0),
                trace_id=request.trace_id,
            )

    def get_config(self) -> LLMAdapterConfig:
        return self._config

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(
        self, request: LLMAdapterRequest
    ) -> tuple[dict[str, Any], list[str]]:
        op = request.operation
        if op == LLMAdapterOperation.complete:
            return self._complete(request.input, request.trace_id)
        if op == LLMAdapterOperation.complete_structured:
            return self._complete_structured(request.input, request.trace_id)
        if op == LLMAdapterOperation.repair_structured_output:
            return self._repair_structured_output(request.input, request.trace_id)
        if op == LLMAdapterOperation.estimate_cost:
            return self._estimate_cost(request.input, request.trace_id)
        raise ValueError(f"Unknown operation: {op}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def _complete(
        self, inp: dict[str, Any], trace_id: str
    ) -> tuple[dict[str, Any], list[str]]:
        messages: list[dict[str, Any]] = inp.get("messages", [])
        system: str = inp.get("system", "")
        max_tokens: int = int(inp.get("max_tokens", 4096))

        self._assert_content_wrapped(messages, LLMAdapterOperation.complete, trace_id)
        cost_limit = self._resolve_cost_limit(inp)
        self._check_cost_budget(
            messages, max_tokens, LLMAdapterOperation.complete, trace_id, cost_limit
        )

        response = self._call_api(messages, system, max_tokens, LLMAdapterOperation.complete, trace_id)
        content = response.content[0].text if response.content else ""

        if response.stop_reason == "end_turn" and not content:
            raise LLMAdapterModuleError(
                LLMAdapterError(
                    operation=LLMAdapterOperation.complete,
                    error_code=LLMAdapterErrorCode.llm_safety_blocked,
                    message="Model returned an empty response (possible safety refusal)",
                    retryable=False,
                    trace_id=trace_id,
                )
            )

        return {
            "content": content,
            "model": response.model,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        }, []

    def _complete_structured(
        self, inp: dict[str, Any], trace_id: str
    ) -> tuple[dict[str, Any], list[str]]:
        output_schema: dict[str, Any] = inp.get("output_schema", {})
        result, warnings = self._complete(inp, trace_id)
        content = _normalize_json_content(result["content"])

        try:
            structured_obj = json.loads(content)
        except json.JSONDecodeError as exc:
            try:
                repair_result, repair_warnings = self._repair_structured_output(
                    {
                        **inp,
                        "bad_output": result["content"],
                        "validation_error": str(exc),
                    },
                    trace_id,
                )
                return repair_result, warnings + repair_warnings
            except LLMAdapterModuleError:
                raise LLMAdapterModuleError(
                    LLMAdapterError(
                        operation=LLMAdapterOperation.complete_structured,
                        error_code=LLMAdapterErrorCode.llm_schema_validation_failed,
                        message=f"Model response is not valid JSON: {exc}",
                        retryable=True,
                        trace_id=trace_id,
                    )
                ) from exc

        if output_schema:
            try:
                jsonschema.validate(structured_obj, output_schema)
            except jsonschema.ValidationError as exc:
                try:
                    repair_result, repair_warnings = self._repair_structured_output(
                        {
                            **inp,
                            "bad_output": result["content"],
                            "validation_error": exc.message,
                        },
                        trace_id,
                    )
                    return repair_result, warnings + repair_warnings
                except LLMAdapterModuleError:
                    raise LLMAdapterModuleError(
                        LLMAdapterError(
                            operation=LLMAdapterOperation.complete_structured,
                            error_code=LLMAdapterErrorCode.llm_schema_validation_failed,
                            message=f"Structured output failed schema validation: {exc.message}",
                            retryable=True,
                            trace_id=trace_id,
                        )
                    ) from exc

        return {
            "structured_object": structured_obj,
            "model": result["model"],
            "usage": result["usage"],
        }, warnings

    def _repair_structured_output(
        self, inp: dict[str, Any], trace_id: str
    ) -> tuple[dict[str, Any], list[str]]:
        messages: list[dict[str, Any]] = inp.get("messages", [])
        output_schema: dict[str, Any] = inp.get("output_schema", {})
        bad_output: str = inp.get("bad_output", "")
        validation_error: str = inp.get("validation_error", "")
        max_tokens: int = int(inp.get("max_tokens", 4096))
        system: str = inp.get("system", "")

        last_error: str = ""
        for attempt in range(1, self._repair_max_attempts + 1):
            feedback = (
                f'{_CONTENT_WRAPPER_OPEN}'
                f"Previous output:\n{bad_output}\n\nValidation error:\n{validation_error or last_error}"
                f"{_CONTENT_WRAPPER_CLOSE}"
            )
            repair_messages = list(messages) + [
                {
                    "role": "user",
                    "content": (
                        f"The previous response did not conform to the required schema. "
                        f"Please fix it.\n\n{feedback}"
                    ),
                }
            ]

            self._check_cost_budget(
                repair_messages,
                max_tokens,
                LLMAdapterOperation.repair_structured_output,
                trace_id,
                self._resolve_cost_limit(inp),
            )
            response = self._call_api(
                repair_messages, system, max_tokens,
                LLMAdapterOperation.repair_structured_output, trace_id
            )
            content = response.content[0].text if response.content else ""
            content = _normalize_json_content(content)

            try:
                obj = json.loads(content)
                if output_schema:
                    jsonschema.validate(obj, output_schema)
                return {
                    "structured_object": obj,
                    "repair_attempts": attempt,
                    "model": response.model,
                    "usage": {
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                    },
                }, []
            except (json.JSONDecodeError, jsonschema.ValidationError) as exc:
                last_error = str(exc)
                bad_output = content

        raise LLMAdapterModuleError(
            LLMAdapterError(
                operation=LLMAdapterOperation.repair_structured_output,
                error_code=LLMAdapterErrorCode.llm_schema_validation_failed,
                message=f"Structured output could not be repaired after {self._repair_max_attempts} attempts",
                retryable=False,
                trace_id=trace_id,
            )
        )

    def _estimate_cost(
        self, inp: dict[str, Any], trace_id: str
    ) -> tuple[dict[str, Any], list[str]]:
        messages: list[dict[str, Any]] = inp.get("messages", [])
        max_tokens: int = int(inp.get("max_tokens", 4096))

        input_text = " ".join(
            m.get("content", "") for m in messages if isinstance(m.get("content"), str)
        )
        estimated_input = max(1, len(input_text) // 4)
        estimated_output = max_tokens

        cost = (
            estimated_input / 1_000_000 * _COST_PER_M_INPUT_USD
            + estimated_output / 1_000_000 * _COST_PER_M_OUTPUT_USD
        )
        within_budget = cost <= self._cost_limit_usd

        return {
            "estimated_input_tokens": estimated_input,
            "estimated_output_tokens": estimated_output,
            "estimated_cost_usd": round(cost, 6),
            "model": self._model,
            "within_budget": within_budget,
        }, []

    # ------------------------------------------------------------------
    # Security helpers
    # ------------------------------------------------------------------

    def _resolve_cost_limit(self, inp: dict[str, Any]) -> float:
        if "cost_limit_usd" in inp:
            return float(inp["cost_limit_usd"])
        return self._cost_limit_usd

    def _assert_content_wrapped(
        self,
        messages: list[dict[str, Any]],
        operation: LLMAdapterOperation,
        trace_id: str,
    ) -> None:
        """Raise if any user message content lacks the required trust wrapper."""
        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                if _CONTENT_WRAPPER_OPEN not in content:
                    raise LLMAdapterModuleError(
                        LLMAdapterError(
                            operation=operation,
                            error_code=LLMAdapterErrorCode.llm_safety_blocked,
                            message=(
                                "User message content must be wrapped in "
                                f"'{_CONTENT_WRAPPER_OPEN}...{_CONTENT_WRAPPER_CLOSE}' tags"
                            ),
                            retryable=False,
                            trace_id=trace_id,
                        )
                    )

    # ------------------------------------------------------------------
    # Cost helpers
    # ------------------------------------------------------------------

    def _check_cost_budget(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int,
        operation: LLMAdapterOperation,
        trace_id: str,
        cost_limit_usd: float | None = None,
    ) -> None:
        limit = self._cost_limit_usd if cost_limit_usd is None else cost_limit_usd
        input_text = " ".join(
            m.get("content", "") for m in messages if isinstance(m.get("content"), str)
        )
        estimated_input = max(1, len(input_text) // 4)
        cost = (
            estimated_input / 1_000_000 * _COST_PER_M_INPUT_USD
            + max_tokens / 1_000_000 * _COST_PER_M_OUTPUT_USD
        )
        if cost > limit:
            raise LLMAdapterModuleError(
                LLMAdapterError(
                    operation=operation,
                    error_code=LLMAdapterErrorCode.llm_cost_limit_exceeded,
                    message=(
                        f"Estimated cost ${cost:.4f} exceeds limit of ${limit:.4f}"
                    ),
                    retryable=False,
                    trace_id=trace_id,
                )
            )

    # ------------------------------------------------------------------
    # API call with timeout
    # ------------------------------------------------------------------

    def _call_api(
        self,
        messages: list[dict[str, Any]],
        system: str,
        max_tokens: int,
        operation: LLMAdapterOperation,
        trace_id: str,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        def _do_call() -> Any:
            return self._client.messages.create(**kwargs)

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_do_call)
                return future.result(timeout=self._timeout_s)
        except FuturesTimeoutError:
            raise LLMAdapterModuleError(
                LLMAdapterError(
                    operation=operation,
                    error_code=LLMAdapterErrorCode.llm_timeout,
                    message=f"LLM call timed out after {self._timeout_s}s",
                    retryable=True,
                    trace_id=trace_id,
                )
            )
        except anthropic.APIConnectionError as exc:
            raise LLMAdapterModuleError(
                LLMAdapterError(
                    operation=operation,
                    error_code=LLMAdapterErrorCode.llm_provider_unavailable,
                    message=f"Anthropic API connection error: {type(exc).__name__}",
                    retryable=True,
                    trace_id=trace_id,
                )
            ) from exc
        except anthropic.APIError as exc:
            raise LLMAdapterModuleError(
                LLMAdapterError(
                    operation=operation,
                    error_code=LLMAdapterErrorCode.llm_provider_unavailable,
                    message=f"Anthropic API error: {type(exc).__name__}",
                    retryable=False,
                    trace_id=trace_id,
                )
            ) from exc

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def _make_metadata(self, t0: float) -> dict[str, Any]:
        return {
            "implementation": "local",
            "contract_version": "0.1.0",
            "model_id": self._model,
            "provider": "anthropic",
            "latency_ms": round((time.monotonic() - t0) * 1000, 2),
        }
