"""Tests for analyze_bottlenecks CLI."""

import json
from pathlib import Path

from ai_workflow_mapper.cli.analyze_bottlenecks import analyze_graph, load_process_graph, main

FIXTURES = Path(__file__).parents[2] / "fixtures" / "bottlenecks"


def test_load_process_graph_from_json():
    graph = load_process_graph(FIXTURES / "synthetic_queue_graph.json")
    assert len(graph.nodes) == 6


def test_load_process_graph_from_mermaid(tmp_path: Path):
    graph = load_process_graph(FIXTURES / "synthetic_queue_graph.json")
    from ai_workflow_mapper.workflow.mermaid_renderer import render_flowchart

    mmd = tmp_path / "flow.mmd"
    mmd.write_text(render_flowchart(graph), encoding="utf-8")

    parsed = load_process_graph(mmd)
    assert {n.id for n in parsed.nodes} == {n.id for n in graph.nodes}


def test_analyze_graph_returns_bottlenecks():
    graph = load_process_graph(FIXTURES / "synthetic_queue_graph.json")
    payload = analyze_graph(graph)
    assert len(payload["bottlenecks"]) >= 1
    assert payload["bottlenecks"][0]["id"].startswith("bn-")


def test_analyze_graph_returns_redundancies():
    graph = load_process_graph(
        Path(__file__).parents[2] / "fixtures" / "redundancies" / "synthetic_duplicate_data_entry.json"
    )
    payload = analyze_graph(graph, analysis="redundancies")
    assert len(payload["redundancies"]) >= 1
    assert payload["redundancies"][0]["id"].startswith("rd-")


def test_analyze_graph_returns_automation_opportunities():
    graph = load_process_graph(
        Path(__file__).parents[2] / "fixtures" / "automation" / "synthetic_notification_task.json"
    )
    payload = analyze_graph(graph, analysis="automation")
    assert len(payload["automation_opportunities"]) >= 1
    assert payload["automation_opportunities"][0]["id"].startswith("ao-")


def test_main_automation_flag(tmp_path: Path, capsys):
    graph = load_process_graph(
        Path(__file__).parents[2] / "fixtures" / "automation" / "synthetic_notification_task.json"
    )
    from ai_workflow_mapper.workflow.mermaid_renderer import render_flowchart

    mmd = tmp_path / "flow.mmd"
    mmd.write_text(render_flowchart(graph), encoding="utf-8")

    code = main(["--automation", "--pretty", str(mmd)])
    captured = capsys.readouterr()

    assert code == 0
    payload = json.loads(captured.out)
    assert "automation_opportunities" in payload
    assert "bottlenecks" not in payload


def test_main_redundancies_flag(tmp_path: Path, capsys):
    graph = load_process_graph(
        Path(__file__).parents[2] / "fixtures" / "redundancies" / "synthetic_duplicate_data_entry.json"
    )
    from ai_workflow_mapper.workflow.mermaid_renderer import render_flowchart

    mmd = tmp_path / "flow.mmd"
    mmd.write_text(render_flowchart(graph), encoding="utf-8")

    code = main(["--redundancies", "--pretty", str(mmd)])
    captured = capsys.readouterr()

    assert code == 0
    payload = json.loads(captured.out)
    assert "redundancies" in payload
    assert "bottlenecks" not in payload
