"""Tests for ProcessExtractor — all LLM calls use a mock adapter."""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import jsonschema
import pytest

from ai_workflow_mapper.platform.contracts.llm_adapter import (
    LLMAdapterOperation,
    LLMAdapterStatus,
)
from ai_workflow_mapper.workflow.domain import JobOptions
from ai_workflow_mapper.workflow.extractor import ProcessExtractor
from ai_workflow_mapper.workflow.normalizer import NormalizedDocument, NormalizedInput

SCHEMAS_DIR = Path(__file__).parents[2] / "schemas"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakeResponse:
    status: LLMAdapterStatus
    result: dict
    warnings: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    operation: LLMAdapterOperation = LLMAdapterOperation.complete_structured
    trace_id: str = "trace-test"
    module_id: str = "llm_adapter"


def _mock_adapter(structured_object: dict | None = None, fail: bool = False) -> MagicMock:
    adapter = MagicMock()
    if fail:
        adapter.handle.return_value = _FakeResponse(
            status=LLMAdapterStatus.failed,
            result={"error": {"error_code": "llm_timeout", "message": "timed out"}},
        )
    else:
        adapter.handle.return_value = _FakeResponse(
            status=LLMAdapterStatus.succeeded,
            result={"structured_object": structured_object or {}},
        )
    return adapter


def _doc(
    filename: str = "sop.txt",
    text: str = "Step 1: Receive request. Step 2: Review request.",
    char_count: int | None = None,
) -> NormalizedDocument:
    return NormalizedDocument(
        filename=filename,
        text=text,
        source_type="sop",
        char_count=char_count if char_count is not None else len(text),
        parser="txt",
    )


def _schema_store() -> dict:
    store: dict = {}
    for path in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        store[data["$id"]] = data
    return store


_VALID_EXTRACTION = {
    "steps": [
        {"id": "step-1", "label": "Receive request", "actor": "Manager"},
        {"id": "step-2", "label": "Review request", "actor": "Analyst"},
    ],
    "handoffs": [{"from_step_id": "step-1", "to_step_id": "step-2"}],
    "decision_points": [],
    "warnings": [],
}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_wrap_satisfies_llm_adapter_gate():
    from ai_workflow_mapper.platform.local.llm_adapter import _CONTENT_WRAPPER_OPEN
    from ai_workflow_mapper.workflow.extractor import _wrap

    wrapped = _wrap("onboarding-sop.pdf", "Step 1: Receive request.")
    assert wrapped.startswith(_CONTENT_WRAPPER_OPEN)
    assert "[source: onboarding-sop.pdf]" in wrapped


def test_build_system_prompt_with_json_examples():
    from ai_workflow_mapper.workflow.extractor import _build_system_prompt, _load_extraction_schema

    prompt = _build_system_prompt(_load_extraction_schema())
    assert '"steps"' in prompt
    assert '"type": "object"' in prompt
    assert '"id": "step_1"' in prompt


def test_extract_happy_path():
    adapter = _mock_adapter(structured_object=_VALID_EXTRACTION)
    normalized = NormalizedInput(documents=[_doc()])
    result = ProcessExtractor(adapter).extract(normalized, trace_id="t1")

    assert len(result.steps) == 2
    assert result.steps[0].id == "step-1"
    assert result.steps[1].actor == "Analyst"
    assert len(result.handoffs) == 1
    assert result.warnings == []


# ---------------------------------------------------------------------------
# Empty / skipped documents
# ---------------------------------------------------------------------------

def test_empty_document_skipped_but_non_empty_sent():
    """Zero-char docs are filtered; non-empty ones still reach the adapter."""
    adapter = _mock_adapter(structured_object=_VALID_EXTRACTION)
    normalized = NormalizedInput(
        documents=[
            _doc("image.pdf", text="", char_count=0),
            _doc("sop.txt"),
        ]
    )
    ProcessExtractor(adapter).extract(normalized, trace_id="t2")

    call_input = adapter.handle.call_args[0][0].input
    user_content = call_input["messages"][0]["content"]
    assert "image.pdf" not in user_content
    assert "sop.txt" in user_content


def test_all_docs_empty_no_llm_call():
    adapter = _mock_adapter()
    normalized = NormalizedInput(documents=[_doc("img.pdf", text="", char_count=0)])
    result = ProcessExtractor(adapter).extract(normalized, trace_id="t3")

    adapter.handle.assert_not_called()
    assert result.steps == []
    assert any("empty text" in w for w in result.warnings)


def test_no_documents_no_llm_call():
    adapter = _mock_adapter()
    normalized = NormalizedInput(documents=[])
    result = ProcessExtractor(adapter).extract(normalized, trace_id="t4")

    adapter.handle.assert_not_called()
    assert any("No documents" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Trust wrapping
# ---------------------------------------------------------------------------

def test_content_wrapped_in_user_messages():
    adapter = _mock_adapter(structured_object=_VALID_EXTRACTION)
    normalized = NormalizedInput(documents=[_doc("sop.txt")])
    ProcessExtractor(adapter).extract(normalized, trace_id="t5")

    call_input = adapter.handle.call_args[0][0].input
    for msg in call_input["messages"]:
        if msg["role"] == "user":
            assert '<process_content trust_level="untrusted">' in msg["content"]
            assert "[source: sop.txt]" in msg["content"]


def test_description_wrapped():
    adapter = _mock_adapter(structured_object=_VALID_EXTRACTION)
    normalized = NormalizedInput(documents=[_doc()])
    ProcessExtractor(adapter).extract(
        normalized,
        trace_id="t6",
        description="Invoice approval process overview.",
    )

    call_input = adapter.handle.call_args[0][0].input
    user_content = call_input["messages"][0]["content"]
    assert "Invoice approval" in user_content
    assert '<process_content trust_level="untrusted">' in user_content
    assert "[source: description]" in user_content


# ---------------------------------------------------------------------------
# LLM failure → partial result (no exception)
# ---------------------------------------------------------------------------

def test_llm_failure_returns_partial():
    adapter = _mock_adapter(fail=True)
    normalized = NormalizedInput(documents=[_doc()])
    result = ProcessExtractor(adapter).extract(normalized, trace_id="t7")

    assert result.steps == []
    assert any("failed" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def test_extraction_validates_against_schema():
    adapter = _mock_adapter(structured_object=_VALID_EXTRACTION)
    normalized = NormalizedInput(documents=[_doc()])
    result = ProcessExtractor(adapter).extract(normalized, trace_id="t8")

    store = _schema_store()
    schema_name = "process_extraction.schema.json"
    schema = json.loads((SCHEMAS_DIR / schema_name).read_text(encoding="utf-8"))
    resolver = jsonschema.RefResolver(
        base_uri=schema["$id"], referrer=schema, store=store
    )
    instance = result.model_dump(mode="json", exclude_none=True)
    jsonschema.validate(instance, schema, resolver=resolver)


# ---------------------------------------------------------------------------
# Cost limit passed through from options
# ---------------------------------------------------------------------------

def test_cost_limit_from_options():
    adapter = _mock_adapter(structured_object=_VALID_EXTRACTION)
    normalized = NormalizedInput(documents=[_doc()])
    options = JobOptions(max_cost_usd=0.50)
    ProcessExtractor(adapter, options).extract(normalized, trace_id="t9")

    call_input = adapter.handle.call_args[0][0].input
    assert call_input["cost_limit_usd"] == pytest.approx(0.50)


def test_cost_limit_default_when_not_set():
    adapter = _mock_adapter(structured_object=_VALID_EXTRACTION)
    normalized = NormalizedInput(documents=[_doc()])
    ProcessExtractor(adapter).extract(normalized, trace_id="t10")

    call_input = adapter.handle.call_args[0][0].input
    assert call_input["cost_limit_usd"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Security: no credentials in output, no document text in logs
# ---------------------------------------------------------------------------

_CRED_PATTERN = re.compile(r"[A-Za-z0-9_\-]{20,}")

def test_extraction_output_no_credentials():
    adapter = _mock_adapter(structured_object=_VALID_EXTRACTION)
    normalized = NormalizedInput(documents=[_doc()])
    result = ProcessExtractor(adapter).extract(normalized, trace_id="t11")

    dumped = json.dumps(result.model_dump(mode="json"))
    for match in _CRED_PATTERN.finditer(dumped):
        token = match.group()
        # Allowlist safe long strings (IDs, labels, etc.)
        assert not token.startswith("sk-"), f"Possible API key in output: {token}"


def test_document_text_not_logged(caplog):
    sensitive_text = "Confidential SOP: employees must not share payroll data."
    adapter = _mock_adapter(structured_object=_VALID_EXTRACTION)
    normalized = NormalizedInput(documents=[_doc(text=sensitive_text)])

    with caplog.at_level(logging.DEBUG, logger="ai_workflow_mapper"):
        ProcessExtractor(adapter).extract(normalized, trace_id="t12")

    for record in caplog.records:
        assert sensitive_text not in record.getMessage(), (
            f"Document text appeared in log: {record.getMessage()}"
        )
