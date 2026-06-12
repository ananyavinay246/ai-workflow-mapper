"""Match process step labels to quotes in normalized source documents."""

from __future__ import annotations

import re

from ai_workflow_mapper.workflow.domain import Evidence
from ai_workflow_mapper.workflow.normalizer import NormalizedInput


def _search_needles(label: str) -> list[str]:
    """Build progressively shorter search needles from a step label."""
    cleaned = re.sub(r"\s+", " ", label.strip())
    if not cleaned:
        return []
    needles = [cleaned[:80], cleaned[:40]]
    words = cleaned.split()
    if len(words) >= 4:
        needles.append(" ".join(words[:4]))
    if len(words) >= 2:
        needles.append(" ".join(words[:2]))
    seen: set[str] = set()
    unique: list[str] = []
    for n in needles:
        n = n.strip()
        if len(n) >= 8 and n.lower() not in seen:
            seen.add(n.lower())
            unique.append(n)
    return unique


def find_evidence(
    normalized: NormalizedInput,
    *,
    node_id: str,
    label: str,
    finding_kind: str = "bottleneck",
) -> tuple[list[Evidence], str | None]:
    """Return evidence items and optional warning when no quote is found."""
    prefix_map = {"bottleneck": "bn", "redundancy": "rd", "automation": "ao"}
    prefix = prefix_map.get(finding_kind, "bn")
    needles = _search_needles(label)
    if not needles:
        return [], f"No evidence needle for {finding_kind} {prefix}-{node_id} (empty label)."

    for doc in normalized.documents:
        if not doc.text or doc.char_count == 0:
            continue
        text = doc.text
        lower_text = text.lower()
        for needle in needles:
            idx = lower_text.find(needle.lower())
            if idx == -1:
                continue
            end = idx + len(needle)
            quote = text[idx:end].strip()
            if len(quote) < 8:
                continue
            return [
                Evidence(
                    quote=quote,
                    source_filename=doc.filename,
                    char_start=idx,
                    char_end=end,
                )
            ], None

    return [], f"No source quote found for {finding_kind} {prefix}-{node_id}."


def find_evidence_for_steps(
    normalized: NormalizedInput,
    *,
    step_ids: list[str],
    labels_by_id: dict[str, str],
    finding_id: str,
    max_quotes: int = 2,
) -> tuple[list[Evidence], list[str]]:
    """Collect up to max_quotes grounded evidence items across affected steps."""
    evidence: list[Evidence] = []
    warnings: list[str] = []

    for step_id in step_ids:
        if len(evidence) >= max_quotes:
            break
        label = labels_by_id.get(step_id, "")
        step_evidence, warning = find_evidence(
            normalized,
            node_id=step_id,
            label=label,
            finding_kind="redundancy",
        )
        if warning:
            warnings.append(warning.replace(f"rd-{step_id}", finding_id))
        if step_evidence:
            evidence.extend(step_evidence)

    return evidence, warnings


def filter_grounded_evidence(
    evidence: list[Evidence],
    normalized: NormalizedInput,
) -> list[Evidence]:
    """Keep only evidence quotes that appear verbatim in normalized documents."""
    grounded: list[Evidence] = []
    for item in evidence:
        for doc in normalized.documents:
            if doc.filename != item.source_filename:
                continue
            if item.quote in doc.text:
                grounded.append(item)
                break
    return grounded
