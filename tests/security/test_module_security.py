"""
Security contract tests for all shared modules.
Acceptance gate: python -m pytest tests/security -v
"""

import base64
import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic as ant
import pytest

from ai_workflow_mapper.platform.contracts.document_loader import (
    DocumentLoaderConfig,
    DocumentLoaderContext,
    DocumentLoaderOperation,
    DocumentLoaderRequest,
)
from ai_workflow_mapper.platform.contracts.llm_adapter import (
    LLMAdapterConfig,
    LLMAdapterContext,
    LLMAdapterOperation,
    LLMAdapterRequest,
)
from ai_workflow_mapper.platform.contracts.report_renderer import (
    ReportRendererConfig,
    ReportRendererContext,
    ReportRendererOperation,
    ReportRendererRequest,
)
from ai_workflow_mapper.platform.local.document_loader import LocalDocumentLoader
from ai_workflow_mapper.platform.local.llm_adapter import LocalLLMAdapter
from ai_workflow_mapper.platform.local.report_renderer import LocalReportRenderer

_TRUST_WRAP = '<process_content trust_level="untrusted">'
_TRUST_CLOSE = "</process_content>"


def _wrap(text: str) -> str:
    return f"{_TRUST_WRAP}{text}{_TRUST_CLOSE}"


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc_loader() -> LocalDocumentLoader:
    return LocalDocumentLoader(
        DocumentLoaderConfig(
            environment="local",
            implementation="local",
            settings={},
            security={},
        )
    )


def _make_llm_adapter() -> LocalLLMAdapter:
    config = LLMAdapterConfig(
        environment="local",
        implementation="local",
        settings={
            "model_id": "claude-sonnet-4-6",
            "timeout_s": 10,
            "cost_limit_usd": 10.0,
            "repair_max_attempts": 2,
        },
        security={},
    )
    with patch.dict(os.environ, {"LLM_API_KEY": "test-key-sec"}):
        return LocalLLMAdapter(config)


def _make_renderer(tmp_path: Path) -> LocalReportRenderer:
    return LocalReportRenderer(
        ReportRendererConfig(
            environment="local",
            implementation="local",
            settings={"output_dir": str(tmp_path / "artifacts")},
            security={},
        )
    )


def _fake_llm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.content = [SimpleNamespace(text=content)]
    resp.model = "claude-sonnet-4-6"
    resp.stop_reason = "end_turn"
    resp.usage = SimpleNamespace(input_tokens=5, output_tokens=10)
    return resp


# ---------------------------------------------------------------------------
# LLM Adapter: content-trust wrapper enforcement
# ---------------------------------------------------------------------------


def test_llm_rejects_unwrapped_user_content():
    """Any user message without the trust wrapper must be blocked before reaching the API."""
    adapter = _make_llm_adapter()
    mock_create = MagicMock()
    with patch.object(adapter._client.messages, "create", mock_create):
        resp = adapter.handle(
            LLMAdapterRequest(
                request_id="sec-001",
                operation=LLMAdapterOperation.complete,
                input={"messages": [{"role": "user", "content": "No wrapper here."}], "max_tokens": 50},
                context=LLMAdapterContext(actor_id="tester", tenant_id="sec", environment="local"),
                trace_id="trace-sec-001",
            )
        )
    mock_create.assert_not_called()
    assert resp.status.value == "failed"
    assert resp.result["error"]["error_code"] == "llm_safety_blocked"


def test_llm_wrapped_content_reaches_api():
    """A correctly wrapped message is allowed through to the API."""
    adapter = _make_llm_adapter()
    fake = _fake_llm_response("OK")
    with patch.object(adapter._client.messages, "create", return_value=fake) as mock_create:
        resp = adapter.handle(
            LLMAdapterRequest(
                request_id="sec-002",
                operation=LLMAdapterOperation.complete,
                input={"messages": [{"role": "user", "content": _wrap("Describe this.")}], "max_tokens": 50},
                context=LLMAdapterContext(actor_id="tester", tenant_id="sec", environment="local"),
                trace_id="trace-sec-002",
            )
        )
    mock_create.assert_called_once()
    assert resp.status.value == "succeeded"


# ---------------------------------------------------------------------------
# LLM Adapter: no secrets in error or metadata
# ---------------------------------------------------------------------------


def test_api_key_not_in_error_on_provider_failure():
    """The API key must never appear in error details when a provider error occurs."""
    adapter = _make_llm_adapter()
    with patch.object(
        adapter._client.messages,
        "create",
        side_effect=ant.APIConnectionError(request=MagicMock()),
    ):
        resp = adapter.handle(
            LLMAdapterRequest(
                request_id="sec-003",
                operation=LLMAdapterOperation.complete,
                input={"messages": [{"role": "user", "content": _wrap("test")}], "max_tokens": 50},
                context=LLMAdapterContext(actor_id="tester", tenant_id="sec", environment="local"),
                trace_id="trace-sec-003",
            )
        )
    error_str = json.dumps(resp.result.get("error", {}))
    assert "test-key-sec" not in error_str
    assert "LLM_API_KEY" not in error_str


def test_prompt_content_not_in_metadata():
    """User-supplied prompt content must not appear in the response metadata."""
    adapter = _make_llm_adapter()
    secret = "CONFIDENTIAL_WORKFLOW_DATA_XYZ"
    fake = _fake_llm_response("done")
    with patch.object(adapter._client.messages, "create", return_value=fake):
        resp = adapter.handle(
            LLMAdapterRequest(
                request_id="sec-004",
                operation=LLMAdapterOperation.complete,
                input={"messages": [{"role": "user", "content": _wrap(secret)}], "max_tokens": 50},
                context=LLMAdapterContext(actor_id="tester", tenant_id="sec", environment="local"),
                trace_id="trace-sec-004",
            )
        )
    assert secret not in json.dumps(resp.metadata)


def test_prompt_content_not_logged(caplog):
    """No prompt content or completion should appear in application logs."""
    adapter = _make_llm_adapter()
    secret = "SUPER_SENSITIVE_PROCESS_DETAIL"
    fake = _fake_llm_response("response_that_should_not_log")
    with caplog.at_level(logging.DEBUG, logger="ai_workflow_mapper"):
        with patch.object(adapter._client.messages, "create", return_value=fake):
            adapter.handle(
                LLMAdapterRequest(
                    request_id="sec-005",
                    operation=LLMAdapterOperation.complete,
                    input={"messages": [{"role": "user", "content": _wrap(secret)}], "max_tokens": 50},
                    context=LLMAdapterContext(actor_id="tester", tenant_id="sec", environment="local"),
                    trace_id="trace-sec-005",
                )
            )
    assert secret not in caplog.text
    assert "response_that_should_not_log" not in caplog.text


# ---------------------------------------------------------------------------
# Document Loader: file content not echoed in metadata
# ---------------------------------------------------------------------------


def test_document_content_not_in_metadata():
    """Raw file content must not appear in the response metadata."""
    loader = _make_doc_loader()
    secret_content = "INTERNAL_SECRET_PROCESS_DESCRIPTION"
    resp = loader.handle(
        DocumentLoaderRequest(
            request_id="sec-006",
            operation=DocumentLoaderOperation.extract_text,
            input={"filename": "process.txt", "content_bytes_b64": _b64(secret_content)},
            context=DocumentLoaderContext(actor_id="tester", tenant_id="sec", environment="local"),
            trace_id="trace-sec-006",
        )
    )
    assert resp.status.value == "succeeded"
    assert secret_content not in json.dumps(resp.metadata)


def test_document_metadata_no_raw_bytes():
    """Metadata must not contain the raw base64-encoded file bytes."""
    loader = _make_doc_loader()
    content = "Some file content"
    content_b64 = _b64(content)
    resp = loader.handle(
        DocumentLoaderRequest(
            request_id="sec-007",
            operation=DocumentLoaderOperation.load_document,
            input={"filename": "doc.txt", "content_bytes_b64": content_b64},
            context=DocumentLoaderContext(actor_id="tester", tenant_id="sec", environment="local"),
            trace_id="trace-sec-007",
        )
    )
    assert content_b64 not in json.dumps(resp.metadata)


# ---------------------------------------------------------------------------
# Report Renderer: artifact content not echoed in result
# ---------------------------------------------------------------------------


def test_artifact_content_not_echoed_in_result(tmp_path):
    """export_artifact must not echo the content field back in its result dict."""
    renderer = _make_renderer(tmp_path)
    secret_report = "# SECRET INTERNAL REPORT\nConfidential process details here."
    resp = renderer.handle(
        ReportRendererRequest(
            request_id="sec-008",
            operation=ReportRendererOperation.export_artifact,
            input={"content": secret_report, "filename": "report.md", "format": "markdown"},
            context=ReportRendererContext(actor_id="tester", tenant_id="sec", environment="local"),
            trace_id="trace-sec-008",
        )
    )
    assert resp.status.value == "succeeded"
    assert "content" not in resp.result
    assert secret_report not in json.dumps(resp.result)
    assert secret_report not in json.dumps(resp.metadata)


# ---------------------------------------------------------------------------
# Contract model: extra fields rejected at boundary
# ---------------------------------------------------------------------------


def test_request_rejects_extra_fields():
    """Request models enforce extra='forbid' — unexpected fields raise ValidationError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DocumentLoaderRequest(
            request_id="sec-009",
            operation=DocumentLoaderOperation.detect_file_type,
            input={"filename": "test.txt"},
            context=DocumentLoaderContext(actor_id="tester", tenant_id="sec", environment="local"),
            trace_id="trace-sec-009",
            unexpected_field="should_fail",  # type: ignore[call-arg]
        )


def test_request_rejects_wrong_module_id():
    """module_id Literal constraint prevents cross-module request spoofing."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DocumentLoaderRequest(
            request_id="sec-010",
            module_id="llm_adapter",  # type: ignore[arg-type]
            operation=DocumentLoaderOperation.detect_file_type,
            input={"filename": "test.txt"},
            context=DocumentLoaderContext(actor_id="tester", tenant_id="sec", environment="local"),
            trace_id="trace-sec-010",
        )
