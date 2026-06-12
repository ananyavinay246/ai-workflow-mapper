"""Graph heuristics for automation opportunity identification."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ai_workflow_mapper.workflow.domain import AutomationEffort, AutomationOpportunity, ProcessGraph

_ANALYZABLE_TYPES = frozenset({"task", "decision"})

_AUTOMATED_KEYWORDS = re.compile(
    r"\b(automated|automatically|system|instant|instantly|api|database|integration|terminal|web service|digital)\b",
    re.IGNORECASE,
)
_RULE_BASED_KEYWORDS = re.compile(
    r"\b(validate|verify|check|calculate|compute|format|generate|assign)\b",
    re.IGNORECASE,
)
_JUDGMENT_KEYWORDS = re.compile(
    r"\b(decide|approve|approval|review|assess|judge)\b",
    re.IGNORECASE,
)
_DATA_ENTRY_KEYWORDS = re.compile(
    r"\b(enter|capture|log|record|input|re-?enter|reenter|copy|paste|transfer|export|import|re-?key|rekey)\b",
    re.IGNORECASE,
)
_APPROVAL_KEYWORDS = re.compile(
    r"\b(approve|approval|review|authorize|sign.?off)\b",
    re.IGNORECASE,
)
_ROUTINE_APPROVAL_KEYWORDS = re.compile(
    r"\b(routine|standard|pre-?approved|if under|threshold|automatically|auto.?approve)\b",
    re.IGNORECASE,
)
_SCHEDULE_KEYWORDS = re.compile(
    r"\b(daily|weekly|monthly|recurring|schedule|scheduled|batch|cron)\b",
    re.IGNORECASE,
)
_NOTIFICATION_KEYWORDS = re.compile(
    r"\b(notify|notification|email|alert|confirmation|confirm|status update|inform|send)\b",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(minute|minutes|min|hour|hours|hr|day|days|week|weeks)s?\b",
    re.IGNORECASE,
)
_FREQUENCY_MULTIPLIER = {
    "daily": 5,
    "day": 5,
    "weekly": 1,
    "week": 1,
    "monthly": 0.25,
    "month": 0.25,
}

_EFFORT_WEIGHT = {"Low": 1, "Medium": 2, "High": 3}


@dataclass
class AutomationCandidate:
    node_id: str
    label: str
    signals: list[str] = field(default_factory=list)
    tool: str | None = None
    frequency: str | None = None
    duration: str | None = None
    handoff_inbound: bool = False

    @property
    def finding_id(self) -> str:
        return f"ao-{self.node_id}"


@dataclass
class _RankedOpportunity:
    opportunity: AutomationOpportunity
    roi_score: float
    signal_count: int


def detect_automation_candidates(graph: ProcessGraph) -> list[AutomationCandidate]:
    """Return deduplicated automation candidates from graph node labels and metadata."""
    if not graph.nodes:
        return []

    node_by_id = {n.id: n for n in graph.nodes}
    incoming_from_handoff = _incoming_from_handoff(graph, node_by_id)
    candidates: dict[str, AutomationCandidate] = {}

    for node in graph.nodes:
        if node.type not in _ANALYZABLE_TYPES:
            continue
        if _is_already_automated(node.label):
            continue

        signals = _detect_signals(
            node,
            handoff_inbound=incoming_from_handoff.get(node.id, False),
        )
        if not signals:
            continue

        candidates[node.id] = AutomationCandidate(
            node_id=node.id,
            label=node.label,
            signals=signals,
            tool=node.tool,
            frequency=node.frequency,
            duration=node.duration,
            handoff_inbound=incoming_from_handoff.get(node.id, False),
        )

    return list(candidates.values())


def candidates_to_opportunities(candidates: list[AutomationCandidate]) -> list[AutomationOpportunity]:
    """Convert candidates to ranked AutomationOpportunity items."""
    ranked: list[_RankedOpportunity] = []
    for candidate in candidates:
        effort = _effort_for_candidate(candidate)
        weekly_minutes = _estimated_weekly_minutes(candidate)
        opportunity = AutomationOpportunity(
            id=candidate.finding_id,
            name=_truncate_name(candidate.label),
            effort=effort,
            time_savings_per_week=_time_savings_template(candidate, weekly_minutes),
            suggested_approach=_suggested_approach_template(candidate),
            evidence=[],
        )
        effort_weight = _EFFORT_WEIGHT[effort or "Medium"]
        roi_score = weekly_minutes / effort_weight if weekly_minutes > 0 else float(len(candidate.signals))
        ranked.append(
            _RankedOpportunity(
                opportunity=opportunity,
                roi_score=roi_score,
                signal_count=len(candidate.signals),
            )
        )

    ranked.sort(
        key=lambda item: (-item.roi_score, -item.signal_count, item.opportunity.name.lower())
    )

    results: list[AutomationOpportunity] = []
    for index, item in enumerate(ranked, start=1):
        effort_label = item.opportunity.effort or "Medium"
        roi_narrative = _roi_narrative(item.opportunity.time_savings_per_week, effort_label)
        results.append(
            item.opportunity.model_copy(
                update={
                    "priority": str(index),
                    "roi": roi_narrative,
                }
            )
        )
    return results


def _detect_signals(node, *, handoff_inbound: bool) -> list[str]:
    signals: list[str] = []
    label = node.label

    if node.type == "task" and _RULE_BASED_KEYWORDS.search(label) and not _JUDGMENT_KEYWORDS.search(label):
        signals.append("rule_based")

    if _DATA_ENTRY_KEYWORDS.search(label) or (node.tool and _DATA_ENTRY_KEYWORDS.search(label)):
        signals.append("data_entry")
    if handoff_inbound and "data_entry" not in signals and _DATA_ENTRY_KEYWORDS.search(label):
        signals.append("data_entry")

    if _APPROVAL_KEYWORDS.search(label) and _ROUTINE_APPROVAL_KEYWORDS.search(label):
        signals.append("repetitive_approval")

    if node.frequency and _schedule_frequency(node.frequency):
        signals.append("scheduled_recurring")
    elif _SCHEDULE_KEYWORDS.search(label):
        signals.append("scheduled_recurring")

    if _NOTIFICATION_KEYWORDS.search(label):
        signals.append("notification_status")

    return signals


def _incoming_from_handoff(graph: ProcessGraph, node_by_id: dict) -> dict[str, bool]:
    incoming: dict[str, bool] = {n.id: False for n in graph.nodes}
    for edge in graph.edges:
        src = node_by_id.get(edge.from_)
        if src and src.type == "handoff" and edge.to in incoming:
            incoming[edge.to] = True
    return incoming


def _is_already_automated(label: str) -> bool:
    if re.search(r"\b(manually|manual)\b", label, re.IGNORECASE):
        return False
    return bool(_AUTOMATED_KEYWORDS.search(label))


def _effort_for_candidate(candidate: AutomationCandidate) -> AutomationEffort:
    if "data_entry" in candidate.signals and candidate.handoff_inbound:
        return "High"
    if "data_entry" in candidate.signals:
        return "Medium"
    if "notification_status" in candidate.signals:
        return "Low"
    if "rule_based" in candidate.signals or "scheduled_recurring" in candidate.signals:
        return "Medium"
    if "repetitive_approval" in candidate.signals:
        return "Medium"
    return "Medium"


def _suggested_approach_template(candidate: AutomationCandidate) -> str:
    approaches: list[str] = []
    if "data_entry" in candidate.signals:
        if candidate.tool:
            approaches.append(f"Zapier/Make integration or API sync for {candidate.tool}")
        else:
            approaches.append("Zapier/Make integration or API sync")
    if "notification_status" in candidate.signals:
        approaches.append("Automated email/Slack notification on status change")
    if "scheduled_recurring" in candidate.signals:
        approaches.append("Scheduled script or cron job")
    if "rule_based" in candidate.signals:
        approaches.append("Form with conditional routing or rules engine")
    if "repetitive_approval" in candidate.signals:
        approaches.append("Auto-approve rules based on thresholds")
    return " ".join(approaches) if approaches else "Evaluate workflow automation tooling."


def _time_savings_template(candidate: AutomationCandidate, weekly_minutes: float) -> str:
    if weekly_minutes <= 0:
        return "Duration/frequency metadata insufficient for weekly estimate."
    if weekly_minutes >= 60:
        hours = weekly_minutes / 60
        text = f"Approximately {hours:.1f} hour(s) per week"
    else:
        text = f"Approximately {int(weekly_minutes)} minute(s) per week"
    if candidate.frequency:
        return f"{text} ({candidate.frequency})."
    return f"{text}."


def _roi_narrative(time_savings: str | None, effort: str) -> str:
    if time_savings and "insufficient" not in (time_savings or "").lower():
        level = "High" if "hour" in (time_savings or "").lower() else "Moderate"
        return f"{level} ({time_savings} saved / {effort} effort)"
    return f"Moderate potential automation value ({effort} effort)"


def _estimated_weekly_minutes(candidate: AutomationCandidate) -> float:
    per_run = _parse_duration_minutes(candidate.duration)
    if per_run is None:
        return 0.0
    multiplier = _frequency_multiplier(candidate.frequency)
    if multiplier is None and _SCHEDULE_KEYWORDS.search(candidate.label or ""):
        multiplier = 1.0
    if multiplier is None:
        return 0.0
    return per_run * multiplier


def _frequency_multiplier(frequency: str | None) -> float | None:
    if not frequency:
        return None
    lower = frequency.lower()
    for key, value in _FREQUENCY_MULTIPLIER.items():
        if key in lower:
            return value
    return None


def _schedule_frequency(frequency: str) -> bool:
    return _frequency_multiplier(frequency) is not None


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


def _truncate_name(label: str) -> str:
    return label if len(label) <= 120 else label[:117] + "..."
