"""Tests for bottleneck graph heuristics."""

import json
from pathlib import Path

from ai_workflow_mapper.workflow.bottleneck_heuristics import (
    candidate_to_finding,
    detect_bottleneck_candidates,
)
from ai_workflow_mapper.workflow.domain import ProcessGraph

FIXTURES = Path(__file__).parents[2] / "fixtures" / "bottlenecks"


def _load_graph(name: str) -> ProcessGraph:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return ProcessGraph.model_validate(data)


def test_queue_graph_flags_approval_step_critical():
    graph = _load_graph("synthetic_queue_graph.json")
    candidates = detect_bottleneck_candidates(graph)
    ids = {c.node_id for c in candidates}
    assert "s2" in ids

    s2 = next(c for c in candidates if c.node_id == "s2")
    assert "queue_keyword" in s2.signals
    assert s2.on_critical_path
    assert s2.in_degree >= 2

    finding = candidate_to_finding(s2)
    assert finding.severity == "Critical"
    assert finding.id == "bn-s2"


def test_spof_graph_flags_critical_path_hub():
    graph = _load_graph("synthetic_spof_graph.json")
    candidates = detect_bottleneck_candidates(graph)
    ids = {c.node_id for c in candidates}
    assert "s1" in ids

    s1 = next(c for c in candidates if c.node_id == "s1")
    assert "critical_path_hub" in s1.signals
    assert s1.on_critical_path

    finding = candidate_to_finding(s1)
    assert finding.severity in {"Critical", "Moderate", "Minor"}


def test_pseudo_nodes_never_flagged():
    graph = _load_graph("synthetic_queue_graph.json")
    candidates = detect_bottleneck_candidates(graph)
    ids = {c.node_id for c in candidates}
    assert "__start__" not in ids
    assert "__end__" not in ids
    assert "__handoff_0__" not in ids


def test_empty_graph_returns_no_candidates():
    graph = ProcessGraph()
    assert detect_bottleneck_candidates(graph) == []
