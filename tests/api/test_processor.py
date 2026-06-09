"""Processor-level tests (no live LLM)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_workflow_mapper.api.models import JobInput
from ai_workflow_mapper.api.processor import process
from ai_workflow_mapper.workflow.domain import JobOptions, ProcessExtraction, ProcessGraph, WorkflowInput

FIXTURE = Path(__file__).parents[2] / "fixtures" / "diagrams" / "sample_process_graph.json"


def _job_input(**options_kwargs) -> JobInput:
    return JobInput(
        request_id="proc-test-001",
        input=WorkflowInput(documents=[]),
        options=JobOptions(**options_kwargs),
    )


def test_process_without_mermaid_has_no_artifacts():
    with patch("ai_workflow_mapper.api.processor._build_llm_adapter", return_value=None):
        out = process(_job_input())
    assert out.artifacts == []
    assert "normalization_summary" in out.result


def test_process_with_mermaid_and_stubbed_graph():
    graph_data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    graph = ProcessGraph.model_validate(graph_data)

    with patch("ai_workflow_mapper.api.processor._build_llm_adapter", return_value=MagicMock()):
        with patch(
            "ai_workflow_mapper.api.processor.ProcessGraphBuilder.build",
            return_value=graph,
        ):
            with patch(
                "ai_workflow_mapper.api.processor.ProcessExtractor.extract",
                return_value=ProcessExtraction(),
            ):
                out = process(_job_input(diagram_formats=["mermaid"]))

    assert out.result.get("process_graph") is not None
    assert len(out.artifacts) == 2
    assert all(a["format"] == "mermaid" for a in out.artifacts)
