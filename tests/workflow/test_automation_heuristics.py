"""Tests for automation opportunity heuristics."""

import json
from pathlib import Path

from ai_workflow_mapper.workflow.automation_heuristics import (
    candidates_to_opportunities,
    detect_automation_candidates,
)
from ai_workflow_mapper.workflow.domain import ProcessGraph

FIXTURES = Path(__file__).parents[2] / "fixtures" / "automation"


def _load_graph(name: str) -> ProcessGraph:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return ProcessGraph.model_validate(data)


def test_notification_task_flagged_low_effort():
    graph = _load_graph("synthetic_notification_task.json")
    candidates = detect_automation_candidates(graph)
    assert len(candidates) == 1
    assert "notification_status" in candidates[0].signals
    opportunities = candidates_to_opportunities(candidates)
    assert opportunities[0].effort == "Low"
    assert opportunities[0].id == "ao-s1"


def test_data_entry_task_flagged():
    graph = _load_graph("synthetic_data_entry_task.json")
    candidates = detect_automation_candidates(graph)
    assert any("data_entry" in c.signals for c in candidates)


def test_rule_based_task_flagged_decision_with_judgment_skipped():
    graph = _load_graph("synthetic_rule_based_task.json")
    candidates = detect_automation_candidates(graph)
    ids = {c.node_id for c in candidates}
    assert "s1" in ids
    assert "s2" not in ids
    assert "rule_based" in next(c for c in candidates if c.node_id == "s1").signals


def test_already_automated_step_skipped():
    graph = ProcessGraph.model_validate(
        {
            "version": "1.0",
            "nodes": [
                {"id": "__start__", "type": "start", "label": "Start"},
                {
                    "id": "s1",
                    "type": "task",
                    "label": "System automatically sends confirmation email",
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
    assert detect_automation_candidates(graph) == []


def test_ranking_assigns_priority_order():
    graph = ProcessGraph.model_validate(
        {
            "version": "1.0",
            "nodes": [
                {"id": "__start__", "type": "start", "label": "Start"},
                {
                    "id": "s1",
                    "type": "task",
                    "label": "Send confirmation email to customer",
                    "duration": "10 minutes",
                    "frequency": "daily",
                },
                {
                    "id": "s2",
                    "type": "task",
                    "label": "Manually enter customer order into ERP",
                    "tool": "ERP",
                    "duration": "20 minutes",
                    "frequency": "daily",
                },
                {"id": "__end__", "type": "end", "label": "End"},
            ],
            "edges": [
                {"from": "__start__", "to": "s1"},
                {"from": "s1", "to": "s2"},
                {"from": "s2", "to": "__end__"},
            ],
            "actors": [],
            "swimlanes": [],
        }
    )
    opportunities = candidates_to_opportunities(detect_automation_candidates(graph))
    assert len(opportunities) == 2
    assert opportunities[0].priority == "1"
    assert opportunities[1].priority == "2"
    assert opportunities[0].id == "ao-s2"
