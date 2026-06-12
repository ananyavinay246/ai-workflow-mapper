"""Tests for AutomationAnalyzer orchestration."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema

from ai_workflow_mapper.platform.contracts.llm_adapter import (
    LLMAdapterOperation,
    LLMAdapterStatus,
)
from ai_workflow_mapper.workflow.automation_analyzer import AutomationAnalyzer
from ai_workflow_mapper.workflow.domain import JobOptions, ProcessGraph
from ai_workflow_mapper.workflow.normalizer import NormalizedDocument, NormalizedInput

FIXTURES = Path(__file__).parents[2] / "fixtures" / "automation"
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


def _validate_automation(item: dict) -> None:
    schema = json.loads((SCHEMAS_DIR / "analysis_findings.schema.json").read_text(encoding="utf-8"))
    automation_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": schema["$defs"]["automation_opportunity"]["required"],
        "properties": schema["$defs"]["automation_opportunity"]["properties"],
    }
    resolver = jsonschema.RefResolver(
        base_uri=schema["$id"], referrer=schema, store=_schema_store()
    )
    jsonschema.validate(item, automation_schema, resolver=resolver)


def _load_graph(name: str) -> ProcessGraph:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return ProcessGraph.model_validate(data)


def test_analyzer_standard_mode():
    graph = _load_graph("synthetic_notification_task.json")
    normalized = NormalizedInput(
        documents=[
            NormalizedDocument(
                filename="sop.txt",
                text="Send confirmation email to customer after order acceptance.",
                source_type="sop",
                char_count=60,
                parser="txt",
            )
        ]
    )
    findings, citations, _ = AutomationAnalyzer(None).analyze(
        graph, normalized, JobOptions(mode="standard"), trace_id="t1"
    )
    assert len(findings) >= 1
    for finding in findings:
        _validate_automation(finding.model_dump(mode="json", exclude_none=True))
    assert any(c["finding_id"].startswith("ao-") for c in citations)


def test_analyzer_thorough_strips_ungrounded_quotes():
    graph = _load_graph("synthetic_notification_task.json")
    normalized = NormalizedInput(
        documents=[
            NormalizedDocument(
                filename="sop.txt",
                text="Send confirmation email to customer.",
                source_type="sop",
                char_count=40,
                parser="txt",
            )
        ]
    )
    finding_id = "ao-s1"
    adapter = MagicMock()
    adapter.handle.return_value = _FakeResponse(
        status=LLMAdapterStatus.succeeded,
        result={
            "structured_object": {
                "automation_opportunities": [
                    {
                        "id": finding_id,
                        "name": "Send confirmation email to customer",
                        "effort": "Low",
                        "roi": "High (est. 1h/week saved / Low effort)",
                        "priority": "1",
                        "time_savings_per_week": "Approximately 1 hour per week.",
                        "suggested_approach": "Automated transactional email on status change.",
                        "evidence": [
                            {
                                "quote": "Send confirmation email to customer",
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
    findings, _, _ = AutomationAnalyzer(adapter).analyze(
        graph, normalized, JobOptions(mode="thorough"), trace_id="t2"
    )
    enriched = next(f for f in findings if f.id == finding_id)
    assert "Automated transactional email" in (enriched.suggested_approach or "")
    assert len(enriched.evidence) == 1


def test_analyzer_llm_failure_preserves_heuristic_findings():
    graph = _load_graph("synthetic_notification_task.json")
    adapter = MagicMock()
    adapter.handle.return_value = _FakeResponse(
        status=LLMAdapterStatus.failed,
        result={"error": {"error_code": "llm_timeout", "message": "timed out"}},
    )
    findings, _, warnings = AutomationAnalyzer(adapter).analyze(
        graph,
        NormalizedInput(documents=[]),
        JobOptions(mode="thorough"),
        trace_id="t3",
    )
    assert len(findings) >= 1
    assert any("LLM enrichment failed" in w for w in warnings)
