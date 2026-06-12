"""Processor report generation tests."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_workflow_mapper.api.models import JobInput
from ai_workflow_mapper.api.processor import process
from ai_workflow_mapper.workflow.domain import JobOptions, ProcessExtraction, ProcessGraph, WorkflowInput

FIXTURE = Path(__file__).parents[2] / "fixtures" / "diagrams" / "sample_process_graph.json"


def _job_input(**options_kwargs) -> JobInput:
    return JobInput(
        request_id="proc-report-001",
        input=WorkflowInput(documents=[]),
        options=JobOptions(**options_kwargs),
    )


def test_process_with_markdown_report_and_stubbed_graph():
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
                with patch(
                    "ai_workflow_mapper.api.processor.BottleneckAnalyzer.analyze",
                    return_value=([], [], []),
                ):
                    with patch(
                        "ai_workflow_mapper.api.processor.RedundancyAnalyzer.analyze",
                        return_value=([], [], []),
                    ):
                        with patch(
                            "ai_workflow_mapper.api.processor.AutomationAnalyzer.analyze",
                            return_value=([], [], []),
                        ):
                            out = process(_job_input(output_format="markdown"))

    analysis = out.result.get("analysis") or {}
    assert analysis.get("executive_summary")
    assert analysis.get("processes")
    assert analysis.get("next_steps")
    report_artifacts = [a for a in out.artifacts if a.get("type") == "report"]
    assert len(report_artifacts) == 1
    assert report_artifacts[0]["format"] == "markdown"
    assert report_artifacts[0]["path"].endswith("report.md")
    assert report_artifacts[0].get("content")
    assert report_artifacts[0]["checksum"].startswith("sha256:")


def test_process_json_format_skips_report_artifact():
    with patch("ai_workflow_mapper.api.processor._build_llm_adapter", return_value=None):
        out = process(_job_input(output_format="json"))
    assert not any(a.get("type") == "report" for a in out.artifacts)
    assert out.result.get("analysis") is None
