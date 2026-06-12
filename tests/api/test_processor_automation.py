"""Processor tests for automation opportunity wiring."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_workflow_mapper.api.models import JobInput
from ai_workflow_mapper.api.processor import process
from ai_workflow_mapper.workflow.domain import JobOptions, ProcessExtraction, ProcessGraph, WorkflowInput

NOTIFICATION_FIXTURE = (
    Path(__file__).parents[2] / "fixtures" / "automation" / "synthetic_notification_task.json"
)


def _job_input(**options_kwargs) -> JobInput:
    return JobInput(
        request_id="ao-proc-001",
        input=WorkflowInput(documents=[]),
        options=JobOptions(**options_kwargs),
    )


def test_process_populates_automation_opportunities_and_citations():
    graph_data = json.loads(NOTIFICATION_FIXTURE.read_text(encoding="utf-8"))
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
                    "ai_workflow_mapper.api.processor.InputNormalizer.normalize",
                ) as mock_norm:
                    from ai_workflow_mapper.workflow.normalizer import (
                        NormalizedDocument,
                        NormalizedInput,
                    )

                    mock_norm.return_value = NormalizedInput(
                        documents=[
                            NormalizedDocument(
                                filename="sop.txt",
                                text="Send confirmation email to customer after acceptance.",
                                source_type="sop",
                                char_count=55,
                                parser="txt",
                            )
                        ]
                    )
                    out = process(_job_input())

    opportunities = (out.result.get("analysis") or {}).get("automation_opportunities") or []
    assert len(opportunities) >= 1
    assert any(o["id"].startswith("ao-") for o in opportunities)
    assert any(c["finding_id"].startswith("ao-") for c in out.citations)


def test_process_adds_empty_automation_warning():
    graph = ProcessGraph.model_validate(
        {
            "version": "1.0",
            "nodes": [
                {"id": "__start__", "type": "start", "label": "Start"},
                {
                    "id": "s1",
                    "type": "task",
                    "label": "System automatically processes payment via API integration",
                    "actor_id": "ops",
                },
                {"id": "__end__", "type": "end", "label": "End"},
            ],
            "edges": [
                {"from": "__start__", "to": "s1"},
                {"from": "s1", "to": "__end__"},
            ],
            "actors": [{"id": "ops", "name": "Operations", "kind": "role"}],
            "swimlanes": [],
        }
    )

    with patch("ai_workflow_mapper.api.processor._build_llm_adapter", return_value=MagicMock()):
        with patch("ai_workflow_mapper.api.processor.ProcessGraphBuilder.build", return_value=graph):
            with patch(
                "ai_workflow_mapper.api.processor.ProcessExtractor.extract",
                return_value=ProcessExtraction(),
            ):
                with patch(
                    "ai_workflow_mapper.api.processor.InputNormalizer.normalize",
                ) as mock_norm:
                    from ai_workflow_mapper.workflow.normalizer import NormalizedInput

                    mock_norm.return_value = NormalizedInput(documents=[])
                    out = process(_job_input())

    assert "No high-confidence automation opportunities found." in out.warnings
