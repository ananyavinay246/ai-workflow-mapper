"""Tests for Mermaid renderers."""

import json
from pathlib import Path

import pytest

from ai_workflow_mapper.workflow.domain import ProcessGraph
from ai_workflow_mapper.workflow.mermaid_renderer import (
    MermaidRenderError,
    render_flowchart,
    render_swimlane,
)

FIXTURE = Path(__file__).parents[2] / "fixtures" / "diagrams" / "sample_process_graph.json"


@pytest.fixture
def sample_graph() -> ProcessGraph:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return ProcessGraph.model_validate(data)


def test_render_flowchart_linear_structure(sample_graph: ProcessGraph):
    content = render_flowchart(sample_graph)
    assert content.startswith("flowchart TD")
    assert "n___start__([Start])" in content or "__start__" in content
    assert "s2{Approved?}" in content or 's2{"Approved?"}' in content
    assert "n___handoff_0__[[Agent -> Operations]]" in content or "__handoff_0__" in content
    assert "-->" in content
    assert '|"Yes: Approved?"|' in content or "Yes: Approved?" in content


def test_render_swimlane_subgraphs(sample_graph: ProcessGraph):
    content = render_swimlane(sample_graph)
    assert content.startswith("flowchart TB")
    assert "subgraph Agent" in content
    assert "subgraph Manager" in content
    assert "subgraph Operations" in content
    assert "s1[Receive request]" in content or 's1["Receive request"]' in content


def test_special_characters_in_label_escaped():
    graph = ProcessGraph.model_validate(
        {
            "version": "1.0",
            "nodes": [
                {"id": "__start__", "type": "start", "label": "Start"},
                {"id": "s1", "type": "task", "label": 'Review "urgent" | priority'},
                {"id": "__end__", "type": "end", "label": "End"},
            ],
            "edges": [
                {"from": "__start__", "to": "s1"},
                {"from": "s1", "to": "__end__"},
            ],
            "actors": [],
            "swimlanes": [],
        }
    )
    content = render_flowchart(graph)
    assert "flowchart TD" in content
    assert "urgent" in content


def test_empty_graph_raises():
    with pytest.raises(MermaidRenderError, match="no nodes"):
        render_flowchart(ProcessGraph())


def test_golden_fixture_snapshot(sample_graph: ProcessGraph):
    flow = render_flowchart(sample_graph)
    swim = render_swimlane(sample_graph)
    assert len(flow.splitlines()) >= 6
    assert len(swim.splitlines()) >= 10
