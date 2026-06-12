"""Run analysis heuristics on an existing Mermaid diagram or ProcessGraph JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Literal

from ai_workflow_mapper.workflow.bottleneck_heuristics import (
    candidate_to_finding as bottleneck_to_finding,
    detect_bottleneck_candidates,
)
from ai_workflow_mapper.workflow.domain import ProcessGraph
from ai_workflow_mapper.workflow.mermaid_parser import MermaidParseError, parse_flowchart_mermaid
from ai_workflow_mapper.workflow.automation_heuristics import (
    candidates_to_opportunities,
    detect_automation_candidates,
)
from ai_workflow_mapper.workflow.redundancy_heuristics import (
    candidate_to_finding as redundancy_to_finding,
    detect_redundancy_candidates,
)

_GRAPH_SUFFIXES = {".json"}
_MERMAID_SUFFIXES = {".mmd", ".mermaid", ".txt", ".md"}
AnalysisKind = Literal["bottlenecks", "redundancies", "automation", "all"]


def load_process_graph(path: Path) -> ProcessGraph:
    """Load a ProcessGraph from Mermaid or JSON."""
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"File not found: {resolved}")

    suffix = resolved.suffix.lower()
    text = resolved.read_text(encoding="utf-8")

    if suffix in _GRAPH_SUFFIXES:
        data = json.loads(text)
        return ProcessGraph.model_validate(data)

    if suffix in _MERMAID_SUFFIXES or text.lstrip().startswith("flowchart "):
        return parse_flowchart_mermaid(text)

    raise ValueError(
        f"Unsupported input {resolved.name!r}. "
        f"Use a process_graph .json or Mermaid flowchart ({', '.join(sorted(_MERMAID_SUFFIXES))})."
    )


def analyze_graph(
    graph: ProcessGraph,
    *,
    analysis: AnalysisKind = "bottlenecks",
    candidates_only: bool = False,
) -> dict[str, Any]:
    """Return analysis payload for a ProcessGraph."""
    payload: dict[str, Any] = {
        "graph": {
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "actors": len(graph.actors),
        }
    }

    if analysis in ("bottlenecks", "all"):
        bn_candidates = detect_bottleneck_candidates(graph)
        if candidates_only:
            payload["bottleneck_candidates"] = [
                {
                    "node_id": c.node_id,
                    "label": c.label,
                    "signals": c.signals,
                    "in_degree": c.in_degree,
                    "out_degree": c.out_degree,
                    "on_critical_path": c.on_critical_path,
                    "downstream_reach": c.downstream_reach,
                }
                for c in bn_candidates
            ]
        else:
            payload["bottlenecks"] = [
                bottleneck_to_finding(c).model_dump(mode="json", exclude_none=True)
                for c in bn_candidates
            ]

    if analysis in ("redundancies", "all"):
        rd_candidates, rd_warnings = detect_redundancy_candidates(graph)
        if rd_warnings:
            payload["warnings"] = rd_warnings
        if candidates_only:
            payload["redundancy_candidates"] = [
                {
                    "signal": c.signal,
                    "finding_id": c.finding_id,
                    "affected_step_ids": c.affected_step_ids,
                    "step_labels": c.step_labels,
                }
                for c in rd_candidates
            ]
        else:
            payload["redundancies"] = [
                redundancy_to_finding(c, graph).model_dump(mode="json", exclude_none=True)
                for c in rd_candidates
            ]

    if analysis in ("automation", "all"):
        ao_candidates = detect_automation_candidates(graph)
        if candidates_only:
            payload["automation_candidates"] = [
                {
                    "node_id": c.node_id,
                    "label": c.label,
                    "signals": c.signals,
                    "tool": c.tool,
                    "frequency": c.frequency,
                    "duration": c.duration,
                }
                for c in ao_candidates
            ]
        else:
            payload["automation_opportunities"] = [
                o.model_dump(mode="json", exclude_none=True)
                for o in candidates_to_opportunities(ao_candidates)
            ]

    return payload


def _print_summary(payload: dict[str, Any], *, analysis: AnalysisKind, candidates_only: bool) -> None:
    graph = payload.get("graph") or {}
    print(
        f"graph: {graph.get('nodes', 0)} nodes, "
        f"{graph.get('edges', 0)} edges, "
        f"{graph.get('actors', 0)} actors",
        file=sys.stderr,
    )
    for warning in payload.get("warnings") or []:
        print(f"warning: {warning}", file=sys.stderr)

    if candidates_only:
        if analysis in ("bottlenecks", "all"):
            items = payload.get("bottleneck_candidates") or []
            print(f"bottleneck_candidates: {len(items)}", file=sys.stderr)
        if analysis in ("redundancies", "all"):
            items = payload.get("redundancy_candidates") or []
            print(f"redundancy_candidates: {len(items)}", file=sys.stderr)
        if analysis in ("automation", "all"):
            items = payload.get("automation_candidates") or []
            print(f"automation_candidates: {len(items)}", file=sys.stderr)
        return

    if analysis in ("bottlenecks", "all"):
        items = payload.get("bottlenecks") or []
        print(f"bottlenecks: {len(items)}", file=sys.stderr)
        for item in items:
            print(
                f"  {item.get('id')}: {item.get('name')} ({item.get('severity')})",
                file=sys.stderr,
            )
    if analysis in ("redundancies", "all"):
        items = payload.get("redundancies") or []
        print(f"redundancies: {len(items)}", file=sys.stderr)
        for item in items:
            print(f"  {item.get('id')}: {item.get('name')}", file=sys.stderr)
    if analysis in ("automation", "all"):
        items = payload.get("automation_opportunities") or []
        print(f"automation_opportunities: {len(items)}", file=sys.stderr)
        for item in items:
            print(
                f"  {item.get('id')}: {item.get('name')} "
                f"(priority={item.get('priority')}, effort={item.get('effort')})",
                file=sys.stderr,
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run bottleneck, redundancy, and/or automation heuristics on an existing "
            "Mermaid flowchart (.mmd) or process_graph JSON without running the full workflow."
        )
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to flowchart.mmd or process_graph.json",
    )
    parser.add_argument(
        "--redundancies",
        action="store_true",
        help="Analyze redundancies only (default: bottlenecks only)",
    )
    parser.add_argument(
        "--automation",
        action="store_true",
        help="Analyze automation opportunities only (default: bottlenecks only)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Analyze bottlenecks, redundancies, and automation opportunities",
    )
    parser.add_argument(
        "--candidates",
        action="store_true",
        help="Emit raw heuristic candidates instead of template findings",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Write JSON results to this file",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON to stdout",
    )
    return parser


def _resolve_analysis(args: argparse.Namespace) -> AnalysisKind:
    if args.all:
        return "all"
    if args.automation:
        return "automation"
    if args.redundancies:
        return "redundancies"
    return "bottlenecks"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    analysis = _resolve_analysis(args)

    try:
        graph = load_process_graph(args.input)
        payload = analyze_graph(
            graph,
            analysis=analysis,
            candidates_only=args.candidates,
        )
    except (FileNotFoundError, ValueError, MermaidParseError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    indent = 2 if args.pretty else None
    text = json.dumps(payload, indent=indent)
    print(text)

    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)

    _print_summary(payload, analysis=analysis, candidates_only=args.candidates)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
