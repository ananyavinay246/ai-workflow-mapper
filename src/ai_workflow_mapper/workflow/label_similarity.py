"""Label normalization and similarity helpers for redundancy detection."""

from __future__ import annotations

import re

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "from",
        "by",
        "at",
        "is",
        "are",
        "be",
        "into",
        "via",
        "through",
    }
)

_DATA_SUBJECT_TOKENS = frozenset(
    {
        "customer",
        "client",
        "order",
        "invoice",
        "address",
        "payment",
        "account",
        "employee",
        "vendor",
        "supplier",
        "product",
        "request",
        "application",
        "shipment",
        "contract",
    }
)


def normalize_label(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation for comparison."""
    cleaned = re.sub(r"\s+", " ", text.strip().lower())
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def tokenize(text: str, *, drop_stopwords: bool = True) -> set[str]:
    """Tokenize a label into significant word tokens."""
    tokens = {t for t in normalize_label(text).split() if len(t) >= 3}
    if drop_stopwords:
        tokens -= _STOPWORDS
    return tokens


def jaccard_similarity(left: str, right: str) -> float:
    """Return Jaccard similarity between two labels."""
    left_tokens = tokenize(left)
    right_tokens = tokenize(right)
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = left_tokens & right_tokens
    union = left_tokens | right_tokens
    return len(intersection) / len(union)


def shared_data_subject_tokens(left: str, right: str) -> set[str]:
    """Return overlapping data-subject tokens between two labels."""
    left_tokens = tokenize(left, drop_stopwords=False)
    right_tokens = tokenize(right, drop_stopwords=False)
    return (left_tokens & right_tokens) & _DATA_SUBJECT_TOKENS
