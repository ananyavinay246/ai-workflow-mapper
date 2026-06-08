"""Tests for ProcessGraphBuilder."""

import json
from pathlib import Path

import jsonschema
import pytest

from ai_workflow_mapper.workflow.domain import (
    DecisionPoint,
    ExtractedStep,
    Handoff,
    ProcessExtraction,
)
from ai_workflow_mapper.workflow.graph_builder import ProcessGraphBuilder

SCHEMAS_DIR = Path(__file__).parents[2] / "schemas"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _step(id: str, label: str, actor: str | None = None, seq: int | None = None) -> ExtractedStep:
    return ExtractedStep(id=id, label=label, actor=actor, sequence_order=seq)


def _schema_store() -> dict:
    store: dict = {}
    for path in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        store[data["$id"]] = data
    return store


def _validate_graph(graph_dict: dict) -> None:
    store = _schema_store()
    schema_name = "process_graph.schema.json"
    schema = json.loads((SCHEMAS_DIR / schema_name).read_text(encoding="utf-8"))
    resolver = jsonschema.RefResolver(
        base_uri=schema["$id"], referrer=schema, store=store
    )
    jsonschema.validate(graph_dict, schema, resolver=resolver)


def _build(extraction: ProcessExtraction) -> dict:
    graph = ProcessGraphBuilder().build(extraction)
    return graph.model_dump(mode="json", by_alias=True, exclude_none=True)


# ---------------------------------------------------------------------------
# Empty extraction
# ---------------------------------------------------------------------------

def test_empty_extraction_returns_valid_minimal_graph():
    graph = ProcessGraphBuilder().build(ProcessExtraction())
    assert graph.version == "1.0"
    assert graph.nodes == []
    assert graph.edges == []
    assert graph.actors == []
    dumped = graph.model_dump(mode="json", by_alias=True, exclude_none=True)
    _validate_graph(dumped)


# ---------------------------------------------------------------------------
# Linear graph
# ---------------------------------------------------------------------------

def test_build_linear_graph():
    extraction = ProcessExtraction(
        steps=[
            _step("s1", "Receive request", seq=0),
            _step("s2", "Review request", seq=1),
            _step("s3", "Approve", seq=2),
        ]
    )
    data = _build(extraction)
    node_ids = [n["id"] for n in data["nodes"]]

    assert "__start__" in node_ids
    assert "__end__" in node_ids
    assert "s1" in node_ids
    assert "s2" in node_ids
    assert "s3" in node_ids

    edge_pairs = {(e["from"], e["to"]) for e in data["edges"]}
    assert ("__start__", "s1") in edge_pairs
    assert ("s1", "s2") in edge_pairs
    assert ("s2", "s3") in edge_pairs
    assert ("s3", "__end__") in edge_pairs


def test_graph_validates_against_schema():
    extraction = ProcessExtraction(
        steps=[
            _step("s1", "Receive", actor="Manager", seq=0),
            _step("s2", "Approve", actor="Director", seq=1),
        ]
    )
    data = _build(extraction)
    _validate_graph(data)


# ---------------------------------------------------------------------------
# Decision node promotion
# ---------------------------------------------------------------------------

def test_decision_node_promotion():
    extraction = ProcessExtraction(
        steps=[
            _step("s1", "Evaluate request"),
        ],
        decision_points=[
            DecisionPoint(
                step_id="s1",
                condition="Is request valid?",
                true_branch_step_id=None,
                false_branch_step_id=None,
            )
        ],
    )
    data = _build(extraction)
    s1_node = next(n for n in data["nodes"] if n["id"] == "s1")
    assert s1_node["type"] == "decision"


def test_decision_branch_edges():
    extraction = ProcessExtraction(
        steps=[
            _step("s1", "Check", seq=0),
            _step("s2", "Approve", seq=1),
            _step("s3", "Reject", seq=2),
        ],
        decision_points=[
            DecisionPoint(
                step_id="s1",
                condition="Valid?",
                true_branch_step_id="s2",
                false_branch_step_id="s3",
            )
        ],
    )
    data = _build(extraction)
    edge_pairs = {(e["from"], e["to"]): e.get("label", "") for e in data["edges"]}
    assert ("s1", "s2") in edge_pairs
    assert ("s1", "s3") in edge_pairs
    assert "Yes" in edge_pairs[("s1", "s2")]
    assert "No" in edge_pairs[("s1", "s3")]


# ---------------------------------------------------------------------------
# Handoff nodes and edges
# ---------------------------------------------------------------------------

def test_handoff_nodes_and_edges():
    extraction = ProcessExtraction(
        steps=[
            _step("s1", "Draft", actor="Writer", seq=0),
            _step("s2", "Review", actor="Editor", seq=1),
        ],
        handoffs=[
            Handoff(
                from_step_id="s1",
                to_step_id="s2",
                from_actor="Writer",
                to_actor="Editor",
            )
        ],
    )
    data = _build(extraction)
    node_types = {n["id"]: n["type"] for n in data["nodes"]}
    handoff_node_id = "__handoff_0__"

    assert handoff_node_id in node_types
    assert node_types[handoff_node_id] == "handoff"

    edge_pairs = {(e["from"], e["to"]) for e in data["edges"]}
    assert ("s1", handoff_node_id) in edge_pairs
    assert (handoff_node_id, "s2") in edge_pairs
    # Direct edge s1→s2 must NOT exist (replaced by handoff node)
    assert ("s1", "s2") not in edge_pairs


# ---------------------------------------------------------------------------
# Actors and swimlanes
# ---------------------------------------------------------------------------

def test_actors_and_swimlanes():
    extraction = ProcessExtraction(
        steps=[
            _step("s1", "Draft", actor="Writer", seq=0),
            _step("s2", "Review", actor="Editor", seq=1),
            _step("s3", "Publish", actor="Writer", seq=2),
        ]
    )
    data = _build(extraction)
    actor_ids = {a["id"] for a in data["actors"]}
    assert "writer" in actor_ids
    assert "editor" in actor_ids
    assert len(data["actors"]) == 2  # deduped

    swimlane_map = {sl["actor_id"]: sl["node_ids"] for sl in data.get("swimlanes", [])}
    assert "writer" in swimlane_map
    assert "s1" in swimlane_map["writer"]
    assert "s3" in swimlane_map["writer"]
    assert "editor" in swimlane_map
    assert "s2" in swimlane_map["editor"]


def test_no_actors_no_swimlanes():
    extraction = ProcessExtraction(
        steps=[_step("s1", "Do something")]
    )
    data = _build(extraction)
    assert data.get("actors", []) == []
    assert data.get("swimlanes", []) == []


# ---------------------------------------------------------------------------
# Sequence ordering
# ---------------------------------------------------------------------------

def test_sequence_order_respected():
    extraction = ProcessExtraction(
        steps=[
            _step("s3", "Third", seq=2),
            _step("s1", "First", seq=0),
            _step("s2", "Second", seq=1),
        ]
    )
    data = _build(extraction)
    node_ids = [n["id"] for n in data["nodes"]]
    # start, s1, s2, s3, end
    pos = {nid: i for i, nid in enumerate(node_ids)}
    assert pos["s1"] < pos["s2"] < pos["s3"]


# ---------------------------------------------------------------------------
# Uncertain step metadata
# ---------------------------------------------------------------------------

def test_uncertain_step_has_metadata():
    extraction = ProcessExtraction(
        steps=[ExtractedStep(id="s1", label="Mystery step", uncertain=True)]
    )
    data = _build(extraction)
    s1 = next(n for n in data["nodes"] if n["id"] == "s1")
    assert s1.get("metadata", {}).get("uncertain") is True
