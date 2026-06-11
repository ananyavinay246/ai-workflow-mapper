"""Tests for RedundancyAnalyzer orchestration."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema

from ai_workflow_mapper.platform.contracts.llm_adapter import (
    LLMAdapterOperation,
    LLMAdapterStatus,
)
from ai_workflow_mapper.workflow.domain import JobOptions, ProcessGraph
from ai_workflow_mapper.workflow.normalizer import NormalizedDocument, NormalizedInput
from ai_workflow_mapper.workflow.redundancy_analyzer import RedundancyAnalyzer

FIXTURES = Path(__file__).parents[2] / "fixtures" / "redundancies"
SCHEMAS_DIR = Path(__file__).parents[2] / "schemas"


@dataclass
class _FakeResponse:
    status: LLMAdapterStatus
    result: dict
    warnings: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    operation: LLMAdapterOperation = LLMAdapterOperation.complete_structured
    trace_id: str = "trace-test"
    module_id: str = "llm_adapter"


def _schema_store() -> dict:
    store: dict = {}
    for path in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        store[data["$id"]] = data
    return store


def _validate_redundancy(item: dict) -> None:
    schema = json.loads((SCHEMAS_DIR / "analysis_findings.schema.json").read_text(encoding="utf-8"))
    redundancy_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": schema["$defs"]["redundancy"]["required"],
        "properties": schema["$defs"]["redundancy"]["properties"],
    }
    resolver = jsonschema.RefResolver(
        base_uri=schema["$id"], referrer=schema, store=_schema_store()
    )
    jsonschema.validate(item, redundancy_schema, resolver=resolver)


def _load_graph(name: str) -> ProcessGraph:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return ProcessGraph.model_validate(data)


def test_analyzer_standard_mode():
    graph = _load_graph("synthetic_duplicate_data_entry.json")
    normalized = NormalizedInput(
        documents=[
            NormalizedDocument(
                filename="sop.txt",
                text="Enter customer order into ERP system before logging in CRM.",
                source_type="sop",
                char_count=60,
                parser="txt",
            )
        ]
    )
    findings, citations, _ = RedundancyAnalyzer(None).analyze(
        graph, normalized, JobOptions(mode="standard"), trace_id="t1"
    )
    assert len(findings) >= 1
    for finding in findings:
        _validate_redundancy(finding.model_dump(mode="json", exclude_none=True))
    assert any(c["finding_id"].startswith("rd-") for c in citations)


def test_analyzer_thorough_strips_ungrounded_quotes():
    graph = _load_graph("synthetic_duplicate_data_entry.json")
    normalized = NormalizedInput(
        documents=[
            NormalizedDocument(
                filename="sop.txt",
                text="Enter customer order into ERP system.",
                source_type="sop",
                char_count=40,
                parser="txt",
            )
        ]
    )
    finding_id = "rd-duplicate_system_entry-s1-s2"
    adapter = MagicMock()
    adapter.handle.return_value = _FakeResponse(
        status=LLMAdapterStatus.succeeded,
        result={
            "structured_object": {
                "redundancies": [
                    {
                        "id": finding_id,
                        "name": "Duplicate data entry across systems",
                        "description": "Order data is entered twice.",
                        "waste_estimate": "Approximately 30 minutes wasted per week.",
                        "affected_steps": ["s1", "s2"],
                        "evidence": [
                            {
                                "quote": "Enter customer order into ERP",
                                "source_filename": "sop.txt",
                            },
                            {
                                "quote": "This quote is not in the document.",
                                "source_filename": "sop.txt",
                            },
                        ],
                    }
                ]
            }
        },
    )
    findings, _, warnings = RedundancyAnalyzer(adapter).analyze(
        graph, normalized, JobOptions(mode="thorough"), trace_id="t2"
    )
    enriched = next((f for f in findings if f.id == finding_id), findings[0])
    assert enriched.waste_estimate is not None
    assert len(enriched.evidence) == 1


def test_analyzer_llm_failure_preserves_heuristic_findings():
    graph = _load_graph("synthetic_overlapping_roles.json")
    adapter = MagicMock()
    adapter.handle.return_value = _FakeResponse(
        status=LLMAdapterStatus.failed,
        result={"error": {"error_code": "llm_timeout", "message": "timed out"}},
    )
    findings, _, warnings = RedundancyAnalyzer(adapter).analyze(
        graph,
        NormalizedInput(documents=[]),
        JobOptions(mode="thorough"),
        trace_id="t3",
    )
    assert len(findings) >= 1
    assert any("LLM enrichment failed" in w for w in warnings)
