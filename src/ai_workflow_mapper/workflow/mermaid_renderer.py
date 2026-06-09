"""Mermaid text renderers for ProcessGraph diagrams."""

from __future__ import annotations

import re

from ai_workflow_mapper.workflow.domain import GraphEdge, GraphNode, ProcessGraph

_QUOTE_LABEL_RE = re.compile(r'["\[\]{}|#;\n\r]')
_EDGE_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s+-->(?:\|[^|]*\|)?\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*$")


class MermaidRenderError(ValueError):
    """Raised when generated Mermaid fails structural validation."""


def render_flowchart(graph: ProcessGraph) -> str:
    """Render a flat top-down flowchart from a ProcessGraph."""
    if not graph.nodes:
        raise MermaidRenderError("Cannot render flowchart: graph has no nodes")

    id_map = {node.id: _mermaid_id(node.id) for node in graph.nodes}
    lines = ["flowchart TD"]
    for node in graph.nodes:
        mid = id_map[node.id]
        lines.append(f"  {mid}{_node_shape(node)}")

    for edge in graph.edges:
        src = id_map.get(edge.from_)
        dst = id_map.get(edge.to)
        if src is None or dst is None:
            raise MermaidRenderError(
                f"Edge references unknown node: {edge.from_} -> {edge.to}"
            )
        if edge.label:
            label = _escape_edge_label(edge.label)
            lines.append(f"  {src} -->|{label}| {dst}")
        else:
            lines.append(f"  {src} --> {dst}")

    content = "\n".join(lines)
    _validate_structure(content, set(id_map.values()))
    return content


def render_swimlane(graph: ProcessGraph) -> str:
    """Render a swimlane diagram using Mermaid subgraphs per actor."""
    if not graph.nodes:
        raise MermaidRenderError("Cannot render swimlane: graph has no nodes")

    id_map = {node.id: _mermaid_id(node.id) for node in graph.nodes}
    actor_names = {a.id: a.name for a in graph.actors}
    node_by_id = {n.id: n for n in graph.nodes}

    lanes: dict[str, list[str]] = {}
    if graph.swimlanes:
        for lane in graph.swimlanes:
            title = actor_names.get(lane.actor_id, lane.actor_id)
            lanes[title] = list(lane.node_ids)
    else:
        for node in graph.nodes:
            if node.type in ("start", "end"):
                continue
            title = actor_names.get(node.actor_id or "", "Unassigned")
            lanes.setdefault(title, []).append(node.id)

    assigned: set[str] = set()
    for node_ids in lanes.values():
        assigned.update(node_ids)

    unassigned = [
        n.id
        for n in graph.nodes
        if n.id not in assigned and n.type not in ("start", "end")
    ]
    if unassigned:
        lanes.setdefault("Unassigned", []).extend(unassigned)

    lines = ["flowchart TB"]
    for lane_title, node_ids in lanes.items():
        safe_title = _escape_subgraph_title(lane_title)
        lines.append(f'  subgraph {safe_title}["{safe_title}"]')
        for node_id in node_ids:
            node = node_by_id.get(node_id)
            if node is None:
                continue
            mid = id_map[node.id]
            lines.append(f"    {mid}{_node_shape(node)}")
        lines.append("  end")

    for node in graph.nodes:
        if node.type in ("start", "end") and node.id not in assigned:
            mid = id_map[node.id]
            lines.append(f"  {mid}{_node_shape(node)}")

    for edge in graph.edges:
        src = id_map.get(edge.from_)
        dst = id_map.get(edge.to)
        if src is None or dst is None:
            raise MermaidRenderError(
                f"Edge references unknown node: {edge.from_} -> {edge.to}"
            )
        if edge.label:
            label = _escape_edge_label(edge.label)
            lines.append(f"  {src} -->|{label}| {dst}")
        else:
            lines.append(f"  {src} --> {dst}")

    content = "\n".join(lines)
    _validate_structure(content, set(id_map.values()))
    return content


def _mermaid_id(node_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", node_id)
    if not safe or safe[0].isdigit():
        safe = f"n_{safe}"
    return safe


def _node_shape(node: GraphNode) -> str:
    label = _format_label(node.label)
    if node.type == "start" or node.type == "end":
        return f"([{label}])"
    if node.type == "decision":
        return f"{{{label}}}"
    if node.type == "handoff":
        return f"[[{label}]]"
    return f"[{label}]"


def _format_label(text: str) -> str:
    cleaned = text.replace("\n", " ").replace("\r", " ").strip()
    cleaned = cleaned.replace('"', "'")
    if _QUOTE_LABEL_RE.search(cleaned):
        return f'"{cleaned}"'
    return cleaned


def _escape_edge_label(text: str) -> str:
    cleaned = text.replace("\n", " ").replace("\r", " ").strip()
    cleaned = cleaned.replace('"', "'")
    return f'"{cleaned}"'


def _escape_subgraph_title(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", text) or "Lane"


def _validate_structure(content: str, node_ids: set[str]) -> None:
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if not lines:
        raise MermaidRenderError("Empty Mermaid output")

    header = lines[0]
    if not header.startswith("flowchart "):
        raise MermaidRenderError(f"Invalid Mermaid header: {header!r}")

    declared: set[str] = set()
    for line in lines[1:]:
        if line.startswith("subgraph ") or line == "end":
            continue
        if "-->" in line:
            match = _EDGE_RE.match(line)
            if not match:
                raise MermaidRenderError(f"Malformed edge line: {line}")
            src, dst = match.group(1), match.group(2)
            if src not in node_ids or dst not in node_ids:
                raise MermaidRenderError(f"Edge references undeclared node: {line}")
            continue
        node_ref = _parse_node_ref(line)
        if node_ref:
            declared.add(node_ref)

    if not declared and node_ids:
        raise MermaidRenderError("No nodes declared in Mermaid output")


def _parse_node_ref(line: str) -> str | None:
    """Extract Mermaid node id from a declaration or edge endpoint."""
    if not line or line.startswith("subgraph"):
        return None
    match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)", line)
    return match.group(1) if match else None
