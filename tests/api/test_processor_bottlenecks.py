"""Processor tests for bottleneck analysis wiring."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_workflow_mapper.api.models import JobInput
from ai_workflow_mapper.api.processor import process
from ai_workflow_mapper.workflow.domain import JobOptions, ProcessExtraction, ProcessGraph, WorkflowInput

QUEUE_FIXTURE = Path(__file__).parents[2] / "fixtures" / "bottlenecks" / "synthetic_queue_graph.json"


def _job_input(**options_kwargs) -> JobInput:
    return JobInput(
        request_id="bn-proc-001",
        input=WorkflowInput(documents=[]),
        options=JobOptions(**options_kwargs),
    )


def test_process_populates_bottlenecks_and_citations():
    graph_data = json.loads(QUEUE_FIXTURE.read_text(encoding="utf-8"))
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
                                text="Managers review and approve request before fulfillment.",
                                source_type="sop",
                                char_count=55,
                                parser="txt",
                            )
                        ]
                    )
                    out = process(_job_input())

    analysis = out.result.get("analysis") or {}
    bottlenecks = analysis.get("bottlenecks") or []
    assert len(bottlenecks) >= 1
    assert any(b["id"] == "bn-s2" for b in bottlenecks)
    assert len(out.citations) >= 1
    assert out.citations[0]["finding_id"].startswith("bn-")
