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
) -> tuple[list[Evidence], str | None]:
    """Return evidence items and optional warning when no quote is found."""
    needles = _search_needles(label)
    if not needles:
        return [], f"No evidence needle for bottleneck bn-{node_id} (empty label)."

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

    return [], f"No source quote found for bottleneck bn-{node_id}."


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
