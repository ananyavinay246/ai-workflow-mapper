"""Graph heuristics for bottleneck detection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ai_workflow_mapper.workflow.domain import BottleneckFinding, ProcessGraph, Severity

_START_ID = "__start__"
_END_ID = "__end__"
_ANALYZABLE_TYPES = frozenset({"task", "decision"})

_QUEUE_KEYWORDS = re.compile(
    r"\b(approve|approval|review|hold|queue|wait|pending|authorize|sign.?off)\b",
    re.IGNORECASE,
)

_AUTOMATED_KEYWORDS = re.compile(
    r"\b(automated|automatically|system|instant|instantly|api|database|integration|terminal|web service|digital)\b",
    re.IGNORECASE,
)

@dataclass
class BottleneckCandidate:
    node_id: str
    label: str
    signals: list[str] = field(default_factory=list)
    in_degree: int = 0
    out_degree: int = 0
    on_critical_path: bool = False
    downstream_reach: int = 0


def detect_bottleneck_candidates(graph: ProcessGraph) -> list[BottleneckCandidate]:
    """Return deduplicated bottleneck candidates from graph metrics."""
    if not graph.nodes:
        return []

    node_by_id = {n.id: n for n in graph.nodes}
    in_degree, out_degree, incoming_from_handoff = _compute_degrees(graph, node_by_id)
    critical_path = _longest_path(graph, node_by_id)
    critical_set = set(critical_path)
    downstream = _downstream_reach(graph)

    cp_actors: dict[str, int] = {}
    for nid in critical_path:
        node = node_by_id.get(nid)
        if node and node.type in _ANALYZABLE_TYPES and node.actor_id:
            cp_actors[node.actor_id] = cp_actors.get(node.actor_id, 0) + 1

    candidates: dict[str, BottleneckCandidate] = {}

    for node in graph.nodes:
        if node.type not in _ANALYZABLE_TYPES:
            continue

        is_automated = bool(_AUTOMATED_KEYWORDS.search(node.label))
        signals: list[str] = []
        indeg = in_degree.get(node.id, 0)
        outdeg = out_degree.get(node.id, 0)
        on_cp = node.id in critical_set

        if indeg >= 3:
            signals.append(f"high_inbound_edges:{indeg}")
        if incoming_from_handoff.get(node.id):
            signals.append("handoff_inbound")
        if _QUEUE_KEYWORDS.search(node.label):
            signals.append("queue_keyword")
        if on_cp and node.actor_id and cp_actors.get(node.actor_id, 0) >= 3:
            signals.append("overburdened_actor_constraint")
        if on_cp and outdeg >= 3:
            signals.append("critical_path_hub")
        if _QUEUE_KEYWORDS.search(node.label) and not is_automated:
            signals.append("queue_keyword")
        elif _QUEUE_KEYWORDS.search(node.label) and is_automated:
            signals.append("automated_transaction")

        if not signals:
            continue

        candidates[node.id] = BottleneckCandidate(
            node_id=node.id,
            label=node.label,
            signals=signals,
            in_degree=indeg,
            out_degree=outdeg,
            on_critical_path=on_cp,
            downstream_reach=downstream.get(node.id, 0),
        )

    return list(candidates.values())


def candidate_to_finding(candidate: BottleneckCandidate) -> BottleneckFinding:
    """Build a template bottleneck finding from a candidate (no evidence yet)."""
    severity = _severity(candidate)
    name = candidate.label if len(candidate.label) <= 120 else candidate.label[:117] + "..."
    signal_text = "; ".join(s.replace("_", " ") for s in candidate.signals)

    description = (
        f"Bottleneck detected at process step '{name}' "
        f"({', '.join(candidate.signals)})."
    )
    impact = (
        f"Affects {candidate.downstream_reach} downstream node(s); "
        f"inbound edges: {candidate.in_degree}, outbound edges: {candidate.out_degree}."
    )
    root_cause = _root_cause_template(candidate)

    return BottleneckFinding(
        id=f"bn-{candidate.node_id}",
        name=name,
        severity=severity,
        description=description,
        impact=impact,
        root_cause_hypothesis=root_cause,
        evidence=[],
    )


def _severity(candidate: BottleneckCandidate) -> Severity:
    queue = "queue_keyword" in candidate.signals
    spof = "overburdened_actor_constraint" in candidate.signals
    handoff = "handoff_inbound" in candidate.signals
    
    # If it contains automated markers, cap its severity to Minor or skip
    if "automated_transaction" in candidate.signals:
        return "Minor"

    # Genuinely severe: A manual queueing step or overloaded actor on the critical path
    if candidate.on_critical_path and (queue or spof):
        return "Critical"
        
    # High convergence or manual handoffs across different teams
    if candidate.in_degree >= 3 or handoff:
        return "Moderate"
        
    return "Minor"


def _root_cause_template(candidate: BottleneckCandidate) -> str:
    parts: list[str] = []
    if "queue_keyword" in candidate.signals:
        parts.append("Step appears to involve approval, review, or queuing.")
    if "handoff_inbound" in candidate.signals:
        parts.append("Work accumulates at a handoff boundary.")
    if "single_point_of_failure" in candidate.signals:
        parts.append("Only one actor performs this step on the critical path.")
    if "high_inbound_edges" in str(candidate.signals):
        parts.append("Multiple upstream paths converge here.")
    if "critical_path_hub" in candidate.signals:
        parts.append("Step branches on the critical path, increasing coordination cost.")
    return " ".join(parts) if parts else "Downstream impact suggests a process constraint."


def _compute_degrees(
    graph: ProcessGraph, node_by_id: dict
) -> tuple[dict[str, int], dict[str, int], dict[str, bool]]:
    in_degree: dict[str, int] = {n.id: 0 for n in graph.nodes}
    out_degree: dict[str, int] = {n.id: 0 for n in graph.nodes}
    incoming_from_handoff: dict[str, bool] = {n.id: False for n in graph.nodes}

    for edge in graph.edges:
        src = edge.from_
        dst = edge.to
        if dst in in_degree:
            in_degree[dst] += 1
        if src in out_degree:
            out_degree[src] += 1
        src_node = node_by_id.get(src)
        if src_node and src_node.type == "handoff" and dst in incoming_from_handoff:
            incoming_from_handoff[dst] = True

    return in_degree, out_degree, incoming_from_handoff


def _longest_path(graph: ProcessGraph, node_by_id: dict) -> list[str]:
    """Computes the longest path in a DAG using topological sorting."""
    # 1. Build adjacency list and track in-degrees
    adjacency: dict[str, list[str]] = {n.id: [] for n in graph.nodes}
    in_degree: dict[str, int] = {n.id: 0 for n in graph.nodes}
    
    for edge in graph.edges:
        if edge.from_ in adjacency:
            adjacency[edge.from_].append(edge.to)
            in_degree[edge.to] = in_degree.get(edge.to, 0) + 1

    # 2. Kahn's algorithm for Topological Sort
    queue = [nid for nid in in_degree if in_degree[nid] == 0]
    topo_order: list[str] = []
    
    while queue:
        curr = queue.pop(0)
        topo_order.append(curr)
        for nxt in adjacency.get(curr, []):
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    if _START_ID not in node_by_id or _END_ID not in node_by_id:
        return []

    # 3. Dynamic programming to find the longest path distances
    # dist[v] stores the length of the longest path from _START_ID to v
    dist = {nid: -float('inf') for nid in node_by_id}
    parent = {nid: "" for nid in node_by_id}
    dist[_START_ID] = 0

    for u in topo_order:
        if dist[u] == -float('inf'):
            continue
        for v in adjacency.get(u, []):
            if dist[u] + 1 > dist[v]:
                dist[v] = dist[u] + 1
                parent[v] = u

    # 4. Reconstruct the path backwards from _END_ID
    if dist[_END_ID] == -float('inf'):
        return []  # End is unreachable from Start

    path = []
    curr = _END_ID
    while curr:
        path.append(curr)
        curr = parent[curr]
        
    return path[::-1]   


def _downstream_reach(graph: ProcessGraph) -> dict[str, int]:
    adjacency: dict[str, list[str]] = {n.id: [] for n in graph.nodes}
    for edge in graph.edges:
        if edge.from_ in adjacency:
            adjacency[edge.from_].append(edge.to)

    reach: dict[str, int] = {}

    def count_reachable(start: str) -> int:
        seen: set[str] = set()
        stack = list(adjacency.get(start, []))
        while stack:
            nid = stack.pop()
            if nid in seen:
                continue
            seen.add(nid)
            stack.extend(adjacency.get(nid, []))
        return len(seen)

    for node in graph.nodes:
        reach[node.id] = count_reachable(node.id)
    return reach
