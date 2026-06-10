"""Tests for BottleneckAnalyzer orchestration."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema

from ai_workflow_mapper.platform.contracts.llm_adapter import (
    LLMAdapterOperation,
    LLMAdapterStatus,
)
from ai_workflow_mapper.workflow.bottleneck_analyzer import BottleneckAnalyzer
from ai_workflow_mapper.workflow.domain import JobOptions, ProcessGraph
from ai_workflow_mapper.workflow.normalizer import NormalizedDocument, NormalizedInput

FIXTURES = Path(__file__).parents[2] / "fixtures" / "bottlenecks"
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


def _validate_bottleneck(item: dict) -> None:
    schema = json.loads((SCHEMAS_DIR / "analysis_findings.schema.json").read_text(encoding="utf-8"))
    bottleneck_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": schema["$defs"]["bottleneck"]["required"],
        "properties": schema["$defs"]["bottleneck"]["properties"],
    }
    resolver = jsonschema.RefResolver(
        base_uri=schema["$id"], referrer=schema, store=_schema_store()
    )
    jsonschema.validate(item, bottleneck_schema, resolver=resolver)


def _load_graph(name: str) -> ProcessGraph:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return ProcessGraph.model_validate(data)


def _normalized(text: str) -> NormalizedInput:
    return NormalizedInput(
        documents=[
            NormalizedDocument(
                filename="sop.txt",
                text=text,
                source_type="sop",
                char_count=len(text),
                parser="txt",
            )
        ]
    )


def test_analyzer_standard_mode_heuristics_and_evidence():
    graph = _load_graph("synthetic_queue_graph.json")
    text = "Agents submit requests. Managers review and approve request before fulfillment."
    findings, citations, warnings = BottleneckAnalyzer(None).analyze(
        graph,
        _normalized(text),
        JobOptions(mode="standard"),
        trace_id="t1",
    )
    assert len(findings) >= 1
    assert any(f.id == "bn-s2" for f in findings)
    for f in findings:
        _validate_bottleneck(f.model_dump(mode="json", exclude_none=True))
    assert len(citations) >= 1
    assert citations[0]["finding_id"].startswith("bn-")
    assert citations[0]["trust_level"] == "untrusted"


def test_analyzer_thorough_strips_ungrounded_llm_quotes():
    graph = _load_graph("synthetic_queue_graph.json")
    text = "Managers review and approve request before fulfillment."
    adapter = MagicMock()
    adapter.handle.return_value = _FakeResponse(
        status=LLMAdapterStatus.succeeded,
        result={
            "structured_object": {
                "bottlenecks": [
                    {
                        "id": "bn-s2",
                        "name": "Review and approve request",
                        "severity": "Critical",
                        "description": "LLM refined description.",
                        "impact": "Blocks downstream fulfillment.",
                        "root_cause_hypothesis": "Approval queue.",
                        "evidence": [
                            {
                                "quote": "Managers review and approve request",
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
    findings, _, warnings = BottleneckAnalyzer(adapter).analyze(
        graph,
        _normalized(text),
        JobOptions(mode="thorough"),
        trace_id="t2",
    )
    s2 = next(f for f in findings if f.id == "bn-s2")
    assert s2.description == "LLM refined description."
    assert len(s2.evidence) == 1
    assert "review and approve" in s2.evidence[0].quote.lower()


def test_analyzer_llm_failure_preserves_heuristic_findings():
    graph = _load_graph("synthetic_queue_graph.json")
    adapter = MagicMock()
    adapter.handle.return_value = _FakeResponse(
        status=LLMAdapterStatus.failed,
        result={"error": {"error_code": "llm_timeout", "message": "timed out"}},
    )
    findings, _, warnings = BottleneckAnalyzer(adapter).analyze(
        graph,
        _normalized("Review and approve request"),
        JobOptions(mode="thorough"),
        trace_id="t3",
    )
    assert len(findings) >= 1
    assert any("LLM enrichment failed" in w for w in warnings)
