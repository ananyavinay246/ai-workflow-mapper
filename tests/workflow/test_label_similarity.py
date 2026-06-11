"""Tests for label similarity helpers."""

from ai_workflow_mapper.workflow.label_similarity import (
    jaccard_similarity,
    shared_data_subject_tokens,
)


def test_jaccard_similarity_identical_labels():
    assert jaccard_similarity(
        "Review submitted application package",
        "Review submitted application package",
    ) == 1.0


def test_jaccard_similarity_partial_overlap():
    score = jaccard_similarity(
        "Collect customer contact details",
        "Gather customer contact information",
    )
    assert score >= 0.3


def test_shared_data_subject_tokens():
    shared = shared_data_subject_tokens(
        "Enter customer order into ERP",
        "Log customer order in CRM",
    )
    assert "customer" in shared
    assert "order" in shared
