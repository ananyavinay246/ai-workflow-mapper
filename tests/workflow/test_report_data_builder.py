"""Tests for ReportDataBuilder."""

import json
from pathlib import Path

from ai_workflow_mapper.workflow.domain import (
    AnalysisFindings,
    AutomationOpportunity,
    BottleneckFinding,
    NormalizationSummary,
    ProcessGraph,
    RedundancyFinding,
)
from ai_workflow_mapper.workflow.report_data_builder import ReportDataBuilder

FIXTURE = Path(__file__).parents[2] / "fixtures" / "diagrams" / "sample_process_graph.json"


def _graph() -> ProcessGraph:
    return ProcessGraph.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


def _summary() -> NormalizationSummary:
    return NormalizationSummary(normalized_documents=2, skipped_documents=1)


def test_process_inventory_from_graph():
    result = ReportDataBuilder().build(_graph(), None, _summary(), job_id="j1")
    assert len(result.findings.processes) == 3
    assert result.findings.processes[0].name == "Receive request"
    assert result.findings.processes[0].owner == "Agent"


def test_executive_summary_mentions_counts():
    analysis = AnalysisFindings(
        bottlenecks=[
            BottleneckFinding(
                id="bn-s2",
                name="Approved?",
                severity="Critical",
                description="Queue",
            )
        ],
        automation_opportunities=[
            AutomationOpportunity(id="ao-s1", name="Notify", priority="1"),
        ],
    )
    result = ReportDataBuilder().build(_graph(), analysis, _summary(), job_id="j1")
    summary = result.findings.executive_summary or ""
    assert "2 normalized" in summary
    assert "Approved?" in summary or "Critical" in summary
    assert "human review" in summary.lower()


def test_next_steps_includes_findings():
    analysis = AnalysisFindings(
        bottlenecks=[
            BottleneckFinding(
                id="bn-s2",
                name="Approval queue",
                severity="Critical",
                description="Slow",
            )
        ],
        redundancies=[
            RedundancyFinding(
                id="rd-1",
                name="Duplicate entry",
                description="Twice",
            )
        ],
        automation_opportunities=[
            AutomationOpportunity(
                id="ao-s1",
                name="Auto email",
                priority="1",
                suggested_approach="Use Zapier",
            )
        ],
    )
    result = ReportDataBuilder().build(_graph(), analysis, _summary(), job_id="j1")
    steps = result.findings.next_steps
    assert 5 <= len(steps) <= 10
    assert any("Approval queue" in s for s in steps)
    assert any("Duplicate entry" in s for s in steps)
    assert any("Auto email" in s for s in steps)
    assert any("skipped" in s.lower() for s in steps)


def test_empty_graph_still_builds_report():
    result = ReportDataBuilder().build(None, None, _summary(), job_id="j1")
    assert result.findings.processes == []
    assert "No process steps" in (result.findings.executive_summary or "")
    assert result.template_data["processes"] == []
