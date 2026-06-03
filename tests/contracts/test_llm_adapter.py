"""Contract tests for LocalLLMAdapter (llm_adapter module). All Anthropic calls are mocked."""

import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import jsonschema

from ai_workflow_mapper.platform.contracts.llm_adapter import (
    LLMAdapterConfig,
    LLMAdapterContext,
    LLMAdapterOperation,
    LLMAdapterRequest,
)
from ai_workflow_mapper.platform.local.llm_adapter import LocalLLMAdapter

SCHEMAS_DIR = Path(__file__).parents[2] / "shared_modules" / "llm_adapter" / "schemas"

_TRUST_WRAP = '<process_content trust_level="untrusted">'
_TRUST_CLOSE = "</process_content>"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


def _make_adapter(extra_settings: dict | None = None) -> LocalLLMAdapter:
    settings: dict = {
        "model_id": "claude-sonnet-4-6",
        "timeout_s": 10,
        "cost_limit_usd": 10.0,
        "repair_max_attempts": 2,
    }
    if extra_settings:
        settings.update(extra_settings)
    config = LLMAdapterConfig(
        environment="local",
        implementation="local",
        settings=settings,
        security={},
    )
    with patch.dict(os.environ, {"LLM_API_KEY": "test-key"}):
        return LocalLLMAdapter(config)


def _make_request(operation: LLMAdapterOperation, inp: dict) -> LLMAdapterRequest:
    return LLMAdapterRequest(
        request_id="test-llm-001",
        operation=operation,
        input=inp,
        context=LLMAdapterContext(actor_id="test", tenant_id="test", environment="local"),
        trace_id="trace-llm-001",
    )


def _wrap(text: str) -> str:
    return f"{_TRUST_WRAP}{text}{_TRUST_CLOSE}"


def _fake_response(content: str, model: str = "claude-sonnet-4-6") -> MagicMock:
    resp = MagicMock()
    resp.content = [SimpleNamespace(text=content)]
    resp.model = model
    resp.stop_reason = "end_turn"
    resp.usage = SimpleNamespace(input_tokens=10, output_tokens=20)
    return resp


# ---------------------------------------------------------------------------
# complete — happy path
# ---------------------------------------------------------------------------


def test_complete_happy_path():
    adapter = _make_adapter()
    fake = _fake_response("Process mapped successfully.")
    with patch.object(adapter._client.messages, "create", return_value=fake):
        resp = adapter.handle(
            _make_request(
                LLMAdapterOperation.complete,
                {
                    "messages": [{"role": "user", "content": _wrap("Describe this process.")}],
                    "max_tokens": 100,
                },
            )
        )
    assert resp.status.value == "succeeded"
    assert resp.result["content"] == "Process mapped successfully."
    assert resp.result["usage"]["input_tokens"] == 10
    assert resp.metadata["provider"] == "anthropic"


def test_complete_missing_trust_wrapper():
    adapter = _make_adapter()
    with patch.object(adapter._client.messages, "create"):
        resp = adapter.handle(
            _make_request(
                LLMAdapterOperation.complete,
                {
                    "messages": [{"role": "user", "content": "No wrapper here."}],
                    "max_tokens": 100,
                },
            )
        )
    assert resp.status.value == "failed"
    assert resp.result["error"]["error_code"] == "llm_safety_blocked"


# ---------------------------------------------------------------------------
# complete_structured — happy path
# ---------------------------------------------------------------------------


def test_complete_structured_happy_path():
    adapter = _make_adapter()
    output_schema = {
        "type": "object",
        "properties": {"steps": {"type": "array", "items": {"type": "string"}}},
        "required": ["steps"],
    }
    fake = _fake_response(json.dumps({"steps": ["Submit", "Approve"]}))
    with patch.object(adapter._client.messages, "create", return_value=fake):
        resp = adapter.handle(
            _make_request(
                LLMAdapterOperation.complete_structured,
                {
                    "messages": [{"role": "user", "content": _wrap("List steps.")}],
                    "output_schema": output_schema,
                    "max_tokens": 200,
                },
            )
        )
    assert resp.status.value == "succeeded"
    assert resp.result["structured_object"]["steps"] == ["Submit", "Approve"]


def test_complete_structured_schema_validation_failed():
    adapter = _make_adapter()
    output_schema = {
        "type": "object",
        "properties": {"steps": {"type": "array"}},
        "required": ["steps"],
    }
    fake = _fake_response(json.dumps({"wrong_key": 123}))
    with patch.object(adapter._client.messages, "create", return_value=fake):
        resp = adapter.handle(
            _make_request(
                LLMAdapterOperation.complete_structured,
                {
                    "messages": [{"role": "user", "content": _wrap("List steps.")}],
                    "output_schema": output_schema,
                    "max_tokens": 200,
                },
            )
        )
    assert resp.status.value == "failed"
    assert resp.result["error"]["error_code"] == "llm_schema_validation_failed"


def test_complete_structured_invalid_json():
    adapter = _make_adapter()
    fake = _fake_response("Not JSON at all.")
    with patch.object(adapter._client.messages, "create", return_value=fake):
        resp = adapter.handle(
            _make_request(
                LLMAdapterOperation.complete_structured,
                {
                    "messages": [{"role": "user", "content": _wrap("List steps.")}],
                    "output_schema": {"type": "object"},
                    "max_tokens": 200,
                },
            )
        )
    assert resp.status.value == "failed"
    assert resp.result["error"]["error_code"] == "llm_schema_validation_failed"


# ---------------------------------------------------------------------------
# repair_structured_output
# ---------------------------------------------------------------------------


def test_repair_structured_output_succeeds_on_second_attempt():
    adapter = _make_adapter()
    output_schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
    call_count = 0

    def side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _fake_response("bad output")
        return _fake_response(json.dumps({"name": "Alice"}))

    with patch.object(adapter._client.messages, "create", side_effect=side_effect):
        resp = adapter.handle(
            _make_request(
                LLMAdapterOperation.repair_structured_output,
                {
                    "messages": [{"role": "user", "content": _wrap("Give name.")}],
                    "output_schema": output_schema,
                    "bad_output": "invalid json",
                    "validation_error": "Not valid JSON",
                    "max_tokens": 100,
                },
            )
        )
    assert resp.status.value == "succeeded"
    assert resp.result["structured_object"]["name"] == "Alice"
    assert resp.result["repair_attempts"] == 2


def test_repair_structured_output_exhausts_attempts():
    adapter = _make_adapter()
    output_schema = {"type": "object", "required": ["name"]}
    fake = _fake_response("still bad")
    with patch.object(adapter._client.messages, "create", return_value=fake):
        resp = adapter.handle(
            _make_request(
                LLMAdapterOperation.repair_structured_output,
                {
                    "messages": [{"role": "user", "content": _wrap("Give name.")}],
                    "output_schema": output_schema,
                    "bad_output": "bad",
                    "validation_error": "bad",
                    "max_tokens": 100,
                },
            )
        )
    assert resp.status.value == "failed"
    assert resp.result["error"]["error_code"] == "llm_schema_validation_failed"
    assert resp.result["error"]["retryable"] is False


# ---------------------------------------------------------------------------
# estimate_cost — no API call
# ---------------------------------------------------------------------------


def test_estimate_cost_no_api_call():
    adapter = _make_adapter()
    mock_create = MagicMock()
    with patch.object(adapter._client.messages, "create", mock_create):
        resp = adapter.handle(
            _make_request(
                LLMAdapterOperation.estimate_cost,
                {
                    "messages": [{"role": "user", "content": "Some text content"}],
                    "max_tokens": 500,
                },
            )
        )
    mock_create.assert_not_called()
    assert resp.status.value == "succeeded"
    assert "estimated_cost_usd" in resp.result
    assert "within_budget" in resp.result
    assert resp.result["model"] == "claude-sonnet-4-6"


def test_estimate_cost_exceeds_budget():
    adapter = _make_adapter({"cost_limit_usd": 0.000001})
    resp = adapter.handle(
        _make_request(
            LLMAdapterOperation.estimate_cost,
            {
                "messages": [{"role": "user", "content": "A" * 10000}],
                "max_tokens": 10000,
            },
        )
    )
    assert resp.result["within_budget"] is False


# ---------------------------------------------------------------------------
# Error scenarios
# ---------------------------------------------------------------------------


def test_timeout_raises_llm_timeout():
    import concurrent.futures

    adapter = _make_adapter()
    with patch.object(
        adapter._client.messages, "create", side_effect=concurrent.futures.TimeoutError
    ):
        resp = adapter.handle(
            _make_request(
                LLMAdapterOperation.complete,
                {
                    "messages": [{"role": "user", "content": _wrap("Process this.")}],
                    "max_tokens": 100,
                },
            )
        )
    assert resp.status.value == "failed"
    assert resp.result["error"]["error_code"] == "llm_timeout"
    assert resp.result["error"]["retryable"] is True


def test_provider_unavailable():
    import anthropic as ant

    adapter = _make_adapter()
    with patch.object(
        adapter._client.messages,
        "create",
        side_effect=ant.APIConnectionError(request=MagicMock()),
    ):
        resp = adapter.handle(
            _make_request(
                LLMAdapterOperation.complete,
                {
                    "messages": [{"role": "user", "content": _wrap("Process this.")}],
                    "max_tokens": 100,
                },
            )
        )
    assert resp.status.value == "failed"
    assert resp.result["error"]["error_code"] == "llm_provider_unavailable"
    assert resp.result["error"]["retryable"] is True


def test_cost_limit_exceeded():
    adapter = _make_adapter({"cost_limit_usd": 0.000001})
    with patch.object(adapter._client.messages, "create"):
        resp = adapter.handle(
            _make_request(
                LLMAdapterOperation.complete,
                {
                    "messages": [{"role": "user", "content": _wrap("A" * 5000)}],
                    "max_tokens": 5000,
                },
            )
        )
    assert resp.status.value == "failed"
    assert resp.result["error"]["error_code"] == "llm_cost_limit_exceeded"


# ---------------------------------------------------------------------------
# Security: no prompts or API key in metadata/errors
# ---------------------------------------------------------------------------


def test_no_prompt_content_in_metadata():
    adapter = _make_adapter()
    secret_text = "SUPER_SECRET_PROCESS"
    fake = _fake_response("OK")
    with patch.object(adapter._client.messages, "create", return_value=fake):
        resp = adapter.handle(
            _make_request(
                LLMAdapterOperation.complete,
                {
                    "messages": [{"role": "user", "content": _wrap(secret_text)}],
                    "max_tokens": 50,
                },
            )
        )
    meta_str = json.dumps(resp.metadata)
    assert secret_text not in meta_str


def test_api_key_not_in_error_details():
    import anthropic as ant

    adapter = _make_adapter()
    with patch.object(
        adapter._client.messages,
        "create",
        side_effect=ant.APIConnectionError(request=MagicMock()),
    ):
        resp = adapter.handle(
            _make_request(
                LLMAdapterOperation.complete,
                {
                    "messages": [{"role": "user", "content": _wrap("test")}],
                    "max_tokens": 50,
                },
            )
        )
    error_str = json.dumps(resp.result.get("error", {}))
    assert "test-key" not in error_str
    assert "LLM_API_KEY" not in error_str


def test_no_prompt_logging(caplog):
    adapter = _make_adapter()
    secret = "MY_SECRET_WORKFLOW"
    fake = _fake_response("done")
    with caplog.at_level(logging.DEBUG, logger="ai_workflow_mapper"):
        with patch.object(adapter._client.messages, "create", return_value=fake):
            adapter.handle(
                _make_request(
                    LLMAdapterOperation.complete,
                    {
                        "messages": [{"role": "user", "content": _wrap(secret)}],
                        "max_tokens": 50,
                    },
                )
            )
    assert secret not in caplog.text


# ---------------------------------------------------------------------------
# Schema conformance
# ---------------------------------------------------------------------------


def test_input_validates_against_schema():
    schema = _load_schema("input.schema.json")
    req = _make_request(
        LLMAdapterOperation.complete,
        {"messages": [{"role": "user", "content": _wrap("test")}], "max_tokens": 50},
    )
    jsonschema.validate(req.model_dump(), schema)


def test_output_validates_against_schema():
    schema = _load_schema("output.schema.json")
    adapter = _make_adapter()
    fake = _fake_response("result text")
    with patch.object(adapter._client.messages, "create", return_value=fake):
        resp = adapter.handle(
            _make_request(
                LLMAdapterOperation.complete,
                {
                    "messages": [{"role": "user", "content": _wrap("test")}],
                    "max_tokens": 50,
                },
            )
        )
    jsonschema.validate(resp.model_dump(exclude_none=True), schema)


def test_error_validates_against_schema():
    schema = _load_schema("error.schema.json")
    adapter = _make_adapter()
    with patch.object(adapter._client.messages, "create"):
        resp = adapter.handle(
            _make_request(
                LLMAdapterOperation.complete,
                {
                    "messages": [{"role": "user", "content": "no wrapper"}],
                    "max_tokens": 50,
                },
            )
        )
    assert resp.status.value == "failed"
    jsonschema.validate(resp.result["error"], schema)


def test_config_validates_against_schema():
    schema = _load_schema("config.schema.json")
    adapter = _make_adapter()
    jsonschema.validate(adapter.get_config().model_dump(exclude_none=True), schema)


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


def test_backward_compatible_fields_stable():
    adapter = _make_adapter()
    fake = _fake_response("OK")
    with patch.object(adapter._client.messages, "create", return_value=fake):
        resp = adapter.handle(
            _make_request(
                LLMAdapterOperation.complete,
                {
                    "messages": [{"role": "user", "content": _wrap("test")}],
                    "max_tokens": 10,
                },
            )
        )
    for field in ("module_id", "operation", "status", "result", "warnings", "metadata", "trace_id"):
        assert hasattr(resp, field)
    assert resp.module_id == "llm_adapter"
    assert resp.trace_id == "trace-llm-001"
