"""Assemble complete analysis report data from workflow outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_workflow_mapper.workflow.domain import (
    AnalysisFindings,
    JobOptions,
    NormalizationSummary,
    ProcessGraph,
    ProcessInventoryItem,
)

_SEVERITY_ORDER = {"Critical": 0, "Moderate": 1, "Minor": 2}


@dataclass
class ReportBuildResult:
    findings: AnalysisFindings
    template_data: dict[str, Any]
    metadata: dict[str, Any]


class ReportDataBuilder:
    """Build validated AnalysisFindings and template payload for report rendering."""

    def build(
        self,
        graph: ProcessGraph | None,
        analysis: AnalysisFindings | None,
        summary: NormalizationSummary,
        options: JobOptions | None = None,
        *,
        job_id: str = "",
    ) -> ReportBuildResult:
        _ = options
        partial = analysis or AnalysisFindings()
        processes = _build_process_inventory(graph)
        executive_summary = _build_executive_summary(graph, partial, summary)
        next_steps = _build_next_steps(partial, summary)

        findings = AnalysisFindings(
            executive_summary=executive_summary,
            processes=processes,
            bottlenecks=list(partial.bottlenecks),
            redundancies=list(partial.redundancies),
            automation_opportunities=list(partial.automation_opportunities),
            next_steps=next_steps,
        )
        template_data = _findings_to_template_data(findings)
        metadata = {
            "job_id": job_id,
            "normalized_documents": summary.normalized_documents,
            "skipped_documents": summary.skipped_documents,
        }
        return ReportBuildResult(
            findings=findings,
            template_data=template_data,
            metadata=metadata,
        )


def _build_process_inventory(graph: ProcessGraph | None) -> list[ProcessInventoryItem]:
    if graph is None or not graph.nodes:
        return []
    actor_names = {a.id: a.name for a in graph.actors}
    items: list[ProcessInventoryItem] = []
    for node in graph.nodes:
        if node.type not in ("task", "decision"):
            continue
        owner = actor_names.get(node.actor_id) if node.actor_id else None
        items.append(
            ProcessInventoryItem(
                name=node.label,
                owner=owner,
                duration=node.duration,
                frequency=node.frequency,
            )
        )
    return items


def _step_count(graph: ProcessGraph | None) -> int:
    if graph is None:
        return 0
    return sum(1 for n in graph.nodes if n.type in ("task", "decision"))


def _build_executive_summary(
    graph: ProcessGraph | None,
    analysis: AnalysisFindings,
    summary: NormalizationSummary,
) -> str:
    steps = _step_count(graph)
    bn_count = len(analysis.bottlenecks)
    rd_count = len(analysis.redundancies)
    ao_count = len(analysis.automation_opportunities)

    parts = [
        "This report summarizes workflow analysis findings from submitted process documents. "
        "Recommendations are analysis-only and require human review before implementation.",
        f"Documents analyzed: {summary.normalized_documents} normalized, "
        f"{summary.skipped_documents} skipped.",
    ]
    if graph is None or steps == 0:
        parts.append("No process steps were extracted from the input corpus.")
    else:
        parts.append(f"The mapped workflow contains {steps} process step(s).")

    parts.append(
        f"Findings: {bn_count} bottleneck(s), {rd_count} redundancy(ies), "
        f"{ao_count} automation opportunity(ies)."
    )

    top_bn = sorted(
        analysis.bottlenecks,
        key=lambda b: (_SEVERITY_ORDER.get(b.severity, 99), b.name),
    )[:3]
    if top_bn:
        bn_lines = ", ".join(f"{b.name} ({b.severity})" for b in top_bn)
        parts.append(f"Top bottlenecks: {bn_lines}.")

    top_ao = sorted(
        analysis.automation_opportunities,
        key=lambda a: (int(a.priority) if a.priority and a.priority.isdigit() else 999, a.name),
    )[:3]
    if top_ao:
        ao_lines = ", ".join(
            f"{a.name} (priority {a.priority or '—'})" for a in top_ao
        )
        parts.append(f"Top automation opportunities: {ao_lines}.")

    return " ".join(parts)


def _build_next_steps(
    analysis: AnalysisFindings,
    summary: NormalizationSummary,
) -> list[str]:
    steps: list[str] = []

    critical = [b for b in analysis.bottlenecks if b.severity == "Critical"]
    for bn in critical[:2]:
        steps.append(f"Address critical bottleneck: {bn.name} — review queue capacity and ownership.")

    moderate = [b for b in analysis.bottlenecks if b.severity == "Moderate"]
    for bn in moderate[:2]:
        if len(steps) >= 6:
            break
        steps.append(f"Reduce moderate bottleneck impact at: {bn.name}.")

    for rd in analysis.redundancies[:2]:
        if len(steps) >= 7:
            break
        steps.append(f"Consolidate redundant work: {rd.name}.")

    top_ao = sorted(
        analysis.automation_opportunities,
        key=lambda a: (int(a.priority) if a.priority and a.priority.isdigit() else 999, a.name),
    )
    for ao in top_ao[:3]:
        if len(steps) >= 9:
            break
        approach = ao.suggested_approach or "Evaluate automation tooling"
        steps.append(f"Implement automation candidate (priority {ao.priority or '—'}): {ao.name} — {approach}.")

    if summary.skipped_documents > 0:
        steps.append(
            f"Review {summary.skipped_documents} skipped document(s) and re-submit if needed."
        )

    if not steps:
        steps.append("No high-priority actions identified; validate extraction quality and re-run with focused inputs.")

    attempts = 0
    while len(steps) < 5 and analysis.bottlenecks and attempts < 10:
        extra = analysis.bottlenecks[len(steps) % len(analysis.bottlenecks)]
        candidate = f"Validate bottleneck finding with process owners: {extra.name}."
        if candidate not in steps:
            steps.append(candidate)
        attempts += 1

    return steps[:10]


def _findings_to_template_data(findings: AnalysisFindings) -> dict[str, Any]:
    return {
        "executive_summary": findings.executive_summary or "",
        "processes": [p.model_dump(mode="json", exclude_none=True) for p in findings.processes],
        "bottlenecks": [
            b.model_dump(mode="json", exclude_none=True) for b in findings.bottlenecks
        ],
        "redundancies": [
            r.model_dump(mode="json", exclude_none=True) for r in findings.redundancies
        ],
        "automation_opportunities": [
            a.model_dump(mode="json", exclude_none=True) for a in findings.automation_opportunities
        ],
        "next_steps": list(findings.next_steps),
    }
