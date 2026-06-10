"""Tests for document evidence matching."""

from ai_workflow_mapper.workflow.evidence_matcher import (
    filter_grounded_evidence,
    find_evidence,
)
from ai_workflow_mapper.workflow.domain import Evidence
from ai_workflow_mapper.workflow.normalizer import NormalizedDocument, NormalizedInput


def _normalized(text: str, filename: str = "sop.txt") -> NormalizedInput:
    return NormalizedInput(
        documents=[
            NormalizedDocument(
                filename=filename,
                text=text,
                source_type="sop",
                char_count=len(text),
                parser="txt",
            )
        ]
    )


def test_find_evidence_matches_label_substring():
    text = "Step 1: Submit request. Step 2: Review and approve request before shipping."
    normalized = _normalized(text)
    evidence, warning = find_evidence(
        normalized, node_id="s2", label="Review and approve request"
    )
    assert warning is None
    assert len(evidence) == 1
    assert evidence[0].source_filename == "sop.txt"
    assert "Review and approve request" in evidence[0].quote
    assert evidence[0].char_start is not None


def test_missing_quote_returns_warning_and_empty_evidence():
    normalized = _normalized("Unrelated process text without the step label.")
    evidence, warning = find_evidence(
        normalized, node_id="s9", label="Place hold on order"
    )
    assert evidence == []
    assert warning is not None
    assert "bn-s9" in warning


def test_filter_grounded_evidence_drops_invented_quotes():
    doc_text = "Manager must review and approve request."
    normalized = _normalized(doc_text)
    grounded = filter_grounded_evidence(
        [
            Evidence(quote="Manager must review and approve request.", source_filename="sop.txt"),
            Evidence(quote="Fabricated quote not in source.", source_filename="sop.txt"),
        ],
        normalized,
    )
    assert len(grounded) == 1
    assert grounded[0].quote.startswith("Manager must")
