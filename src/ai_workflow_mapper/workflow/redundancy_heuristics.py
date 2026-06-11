"""Graph heuristics for redundancy detection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ai_workflow_mapper.workflow.domain import GraphNode, ProcessGraph, RedundancyFinding
from ai_workflow_mapper.workflow.label_similarity import (
    jaccard_similarity,
    shared_data_subject_tokens,
)

_ANALYZABLE_TYPES = frozenset({"task", "decision"})
_PAIRWISE_NODE_CAP = 500

_APPROVAL_KEYWORDS = re.compile(
    r"\b(approve|approval|review|authorize|sign.?off|signoff)\b",
    re.IGNORECASE,
)
_DATA_ENTRY_KEYWORDS = re.compile(
    r"\b(enter|capture|log|record|input|re-?enter|reenter|type|key)\b",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(minute|minutes|min|hour|hours|hr|day|days|week|weeks)s?\b",
    re.IGNORECASE,
)

_SIGNAL_NAMES = {
    "duplicate_approval": "Duplicate approval steps",
    "duplicate_system_entry": "Duplicate data entry across systems",
    "duplicate_info_request": "Duplicate information request",
    "overlapping_roles": "Overlapping role responsibilities",
}


@dataclass
class RedundancyCandidate:
    signal: str
    affected_step_ids: list[str]
    step_labels: dict[str, str] = field(default_factory=dict)

    @property
    def finding_id(self) -> str:
        step_a, step_b = sorted(self.affected_step_ids)
        if self.signal == "duplicate_approval":
            return f"rd-dup-approval-{step_a}-{step_b}"
        return f"rd-{self.signal}-{step_a}-{step_b}"


def detect_redundancy_candidates(
    graph: ProcessGraph,
) -> tuple[list[RedundancyCandidate], list[str]]:
    """Return deduplicated redundancy candidates and optional analyzer warnings."""
    warnings: list[str] = []
    if not graph.nodes:
        return [], warnings

    node_by_id = {n.id: n for n in graph.nodes}
    analyzable = [n for n in graph.nodes if n.type in _ANALYZABLE_TYPES]

    if len(analyzable) > _PAIRWISE_NODE_CAP:
        warnings.append(
            f"Redundancy pairwise analysis skipped: {len(analyzable)} analyzable nodes "
            f"exceeds cap of {_PAIRWISE_NODE_CAP}."
        )
        pair_nodes: list[GraphNode] = []
    else:
        pair_nodes = analyzable

    candidates: dict[str, RedundancyCandidate] = {}

    for edge in graph.edges:
        src = node_by_id.get(edge.from_)
        dst = node_by_id.get(edge.to)
        if not src or not dst:
            continue
        if src.type not in _ANALYZABLE_TYPES or dst.type not in _ANALYZABLE_TYPES:
            continue
        if not _APPROVAL_KEYWORDS.search(src.label) or not _APPROVAL_KEYWORDS.search(dst.label):
            continue
        candidate = RedundancyCandidate(
            signal="duplicate_approval",
            affected_step_ids=[src.id, dst.id],
            step_labels={src.id: src.label, dst.id: dst.label},
        )
        candidates[candidate.finding_id] = candidate

    consecutive_pairs = {(edge.from_, edge.to) for edge in graph.edges}

    for i, left in enumerate(pair_nodes):
        for right in pair_nodes[i + 1 :]:
            pair_key = tuple(sorted((left.id, right.id)))
            _detect_pair_redundancies(
                left,
                right,
                pair_key=pair_key,
                consecutive_pairs=consecutive_pairs,
                candidates=candidates,
            )

    return list(candidates.values()), warnings


def candidate_to_finding(candidate: RedundancyCandidate, graph: ProcessGraph) -> RedundancyFinding:
    """Build a template redundancy finding from a candidate."""
    node_by_id = {n.id: n for n in graph.nodes}
    labels = [
        candidate.step_labels.get(step_id) or node_by_id[step_id].label
        for step_id in candidate.affected_step_ids
        if step_id in node_by_id
    ]
    label_text = "; ".join(labels)
    name = _SIGNAL_NAMES.get(candidate.signal, "Process redundancy")

    description = _description_template(candidate.signal, label_text)
    waste_estimate = _waste_estimate_template(candidate.affected_step_ids, node_by_id)

    return RedundancyFinding(
        id=candidate.finding_id,
        name=name,
        description=description,
        waste_estimate=waste_estimate,
        affected_steps=list(candidate.affected_step_ids),
        evidence=[],
    )


def _detect_pair_redundancies(
    left: GraphNode,
    right: GraphNode,
    *,
    pair_key: tuple[str, str],
    consecutive_pairs: set[tuple[str, str]],
    candidates: dict[str, RedundancyCandidate],
) -> None:
    if left.id == right.id:
        return

    similarity = jaccard_similarity(left.label, right.label)

    if (
        left.tool
        and right.tool
        and left.tool.strip().lower() != right.tool.strip().lower()
        and _DATA_ENTRY_KEYWORDS.search(left.label)
        and _DATA_ENTRY_KEYWORDS.search(right.label)
        and shared_data_subject_tokens(left.label, right.label)
    ):
        candidate = RedundancyCandidate(
            signal="duplicate_system_entry",
            affected_step_ids=[left.id, right.id],
            step_labels={left.id: left.label, right.id: right.label},
        )
        candidates[candidate.finding_id] = candidate

    is_consecutive = pair_key in consecutive_pairs or tuple(reversed(pair_key)) in consecutive_pairs
    same_actor = left.actor_id and right.actor_id and left.actor_id == right.actor_id

    if same_actor and similarity >= 0.65 and not (
        is_consecutive
        and _APPROVAL_KEYWORDS.search(left.label)
        and _APPROVAL_KEYWORDS.search(right.label)
    ):
        candidate = RedundancyCandidate(
            signal="duplicate_info_request",
            affected_step_ids=[left.id, right.id],
            step_labels={left.id: left.label, right.id: right.label},
        )
        candidates[candidate.finding_id] = candidate

    different_actors = (
        left.actor_id
        and right.actor_id
        and left.actor_id != right.actor_id
        and left.type == "task"
        and right.type == "task"
    )
    if different_actors and similarity >= 0.75:
        candidate = RedundancyCandidate(
            signal="overlapping_roles",
            affected_step_ids=[left.id, right.id],
            step_labels={left.id: left.label, right.id: right.label},
        )
        candidates[candidate.finding_id] = candidate


def _description_template(signal: str, label_text: str) -> str:
    templates = {
        "duplicate_approval": (
            f"Two sequential approval or review steps detected: {label_text}."
        ),
        "duplicate_system_entry": (
            f"The same data appears to be entered into multiple systems: {label_text}."
        ),
        "duplicate_info_request": (
            f"The same actor may be gathering similar information more than once: {label_text}."
        ),
        "overlapping_roles": (
            f"Different roles appear to perform substantially similar work: {label_text}."
        ),
    }
    return templates.get(signal, f"Redundant process steps detected: {label_text}.")


def _waste_estimate_template(step_ids: list[str], node_by_id: dict[str, GraphNode]) -> str:
    total_minutes = 0.0
    parsed_any = False
    frequency_hint: str | None = None

    for step_id in step_ids:
        node = node_by_id.get(step_id)
        if not node:
            continue
        if node.frequency and not frequency_hint:
            frequency_hint = node.frequency
        minutes = _parse_duration_minutes(node.duration)
        if minutes is not None:
            total_minutes += minutes
            parsed_any = True

    if not parsed_any:
        return "Redundant steps identified; duration metadata insufficient for numeric estimate."

    if total_minutes >= 60:
        hours = total_minutes / 60
        estimate = f"Approximately {hours:.1f} hour(s) of redundant effort per process run"
    else:
        estimate = f"Approximately {int(total_minutes)} minute(s) of redundant effort per process run"

    if frequency_hint:
        estimate += f" ({frequency_hint})."
    else:
        estimate += "."
    return estimate


def _parse_duration_minutes(duration: str | None) -> float | None:
    if not duration:
        return None
    match = _DURATION_RE.search(duration)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("min"):
        return value
    if unit.startswith("hour") or unit == "hr":
        return value * 60
    if unit.startswith("day"):
        return value * 60 * 8
    if unit.startswith("week"):
        return value * 60 * 40
    return None
