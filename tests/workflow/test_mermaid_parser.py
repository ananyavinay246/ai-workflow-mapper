"""Tests for Mermaid flowchart parsing back into ProcessGraph."""

import json
from pathlib import Path

import pytest

from ai_workflow_mapper.workflow.bottleneck_heuristics import detect_bottleneck_candidates
from ai_workflow_mapper.workflow.domain import ProcessGraph
from ai_workflow_mapper.workflow.mermaid_parser import MermaidParseError, parse_flowchart_mermaid
from ai_workflow_mapper.workflow.mermaid_renderer import render_flowchart

FIXTURES = Path(__file__).parents[2] / "fixtures" / "bottlenecks"
ARTIFACT = (
    Path(__file__).parents[2]
    / "src"
    / "ai_workflow_mapper"
    / "cli"
    / "artifacts"
    / "cli-8eb0025f-4f7c-4e06-9089-bb6211222505"
    / "flowchart.mmd"
)


def _load_graph(name: str) -> ProcessGraph:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return ProcessGraph.model_validate(data)


def test_round_trip_flowchart_preserves_nodes_and_edges():
    graph = _load_graph("synthetic_queue_graph.json")
    mermaid = render_flowchart(graph)
    parsed = parse_flowchart_mermaid(mermaid)

    assert len(parsed.nodes) == len(graph.nodes)
    assert len(parsed.edges) == len(graph.edges)
    assert {n.id for n in parsed.nodes} == {n.id for n in graph.nodes}


def test_parse_real_job_flowchart_finds_candidates():
    if not ARTIFACT.is_file():
        pytest.skip("Local artifact flowchart not present")

    parsed = parse_flowchart_mermaid(ARTIFACT.read_text(encoding="utf-8"))
    candidates = detect_bottleneck_candidates(parsed)

    assert len(parsed.nodes) >= 10
    assert len(candidates) >= 1
    assert any("queue_keyword" in c.signals for c in candidates)


def test_parse_rejects_non_flowchart():
    with pytest.raises(MermaidParseError, match="flowchart header"):
        parse_flowchart_mermaid("graph LR\n  a --> b")
