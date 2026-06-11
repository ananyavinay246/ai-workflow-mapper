"""Processor tests for redundancy analysis wiring."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_workflow_mapper.api.models import JobInput
from ai_workflow_mapper.api.processor import process
from ai_workflow_mapper.workflow.domain import JobOptions, ProcessExtraction, ProcessGraph, WorkflowInput

DATA_ENTRY_FIXTURE = (
    Path(__file__).parents[2] / "fixtures" / "redundancies" / "synthetic_duplicate_data_entry.json"
)


def _job_input(**options_kwargs) -> JobInput:
    return JobInput(
        request_id="rd-proc-001",
        input=WorkflowInput(documents=[]),
        options=JobOptions(**options_kwargs),
    )


def test_process_populates_redundancies_and_citations():
    graph_data = json.loads(DATA_ENTRY_FIXTURE.read_text(encoding="utf-8"))
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
                                text="Enter customer order into ERP system and log in CRM.",
                                source_type="sop",
                                char_count=55,
                                parser="txt",
                            )
                        ]
                    )
                    out = process(_job_input())

    redundancies = (out.result.get("analysis") or {}).get("redundancies") or []
    assert len(redundancies) >= 1
    assert any(r["id"].startswith("rd-") for r in redundancies)
    assert any(c["finding_id"].startswith("rd-") for c in out.citations)
