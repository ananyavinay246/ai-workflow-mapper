"""Tests for redundancy graph heuristics."""

import json
from pathlib import Path

from ai_workflow_mapper.workflow.domain import ProcessGraph
from ai_workflow_mapper.workflow.redundancy_heuristics import (
    candidate_to_finding,
    detect_redundancy_candidates,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "redundancies"


def _load_graph(name: str) -> ProcessGraph:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return ProcessGraph.model_validate(data)


def test_duplicate_approval_chain():
    graph = _load_graph("synthetic_duplicate_approval.json")
    candidates, _ = detect_redundancy_candidates(graph)
    signals = {c.signal for c in candidates}
    assert "duplicate_approval" in signals
    approval = next(c for c in candidates if c.signal == "duplicate_approval")
    assert set(approval.affected_step_ids) == {"s2", "s3"}
    finding = candidate_to_finding(approval, graph)
    assert finding.id.startswith("rd-dup-approval-")


def test_duplicate_system_entry():
    graph = _load_graph("synthetic_duplicate_data_entry.json")
    candidates, _ = detect_redundancy_candidates(graph)
    assert any(c.signal == "duplicate_system_entry" for c in candidates)


def test_overlapping_roles():
    graph = _load_graph("synthetic_overlapping_roles.json")
    candidates, _ = detect_redundancy_candidates(graph)
    assert any(c.signal == "overlapping_roles" for c in candidates)


def test_duplicate_info_request():
    graph = ProcessGraph.model_validate(
        {
            "version": "1.0",
            "nodes": [
                {"id": "__start__", "type": "start", "label": "Start"},
            {
                "id": "s1",
                "type": "task",
                "label": "Collect customer contact details",
                "actor_id": "agent",
            },
            {"id": "s2", "type": "task", "label": "Validate shipping address", "actor_id": "agent"},
            {
                "id": "s3",
                "type": "task",
                "label": "Collect customer contact details again",
                "actor_id": "agent",
            },
                {"id": "__end__", "type": "end", "label": "End"},
            ],
            "edges": [
                {"from": "__start__", "to": "s1"},
                {"from": "s1", "to": "s2"},
                {"from": "s2", "to": "s3"},
                {"from": "s3", "to": "__end__"},
            ],
            "actors": [{"id": "agent", "name": "Agent", "kind": "role"}],
            "swimlanes": [],
        }
    )
    candidates, _ = detect_redundancy_candidates(graph)
    assert any(c.signal == "duplicate_info_request" for c in candidates)


def test_pseudo_nodes_not_flagged_alone():
    graph = _load_graph("synthetic_duplicate_approval.json")
    candidates, _ = detect_redundancy_candidates(graph)
    for candidate in candidates:
        for step_id in candidate.affected_step_ids:
            assert step_id not in {"__start__", "__end__"}
