from __future__ import annotations

import pytest

from retrieval_provenance import attach_source_labels, merge_source_labels, normalize_source_labels


def test_normalize_source_labels_accepts_delimited_strings() -> None:
    assert normalize_source_labels("BM25+dense|Graph; rerank") == [
        "bm25",
        "dense",
        "graph",
        "rerank",
    ]


def test_merge_source_labels_preserves_first_seen_order() -> None:
    assert merge_source_labels(["dense", "graph"], "bm25+dense", ["rrf"]) == [
        "dense",
        "graph",
        "bm25",
        "rrf",
    ]


def test_attach_source_labels_copies_hit_and_sets_hint() -> None:
    original = {"chunk_id": "c1", "source_labels": ["dense"]}

    updated = attach_source_labels(original, ["graph", "rrf"])

    assert original == {"chunk_id": "c1", "source_labels": ["dense"]}
    assert updated["source_labels"] == ["dense", "graph", "rrf"]
    assert updated["source_hint"] == "dense+graph+rrf"


def test_attach_source_labels_rejects_malformed_hit() -> None:
    with pytest.raises(TypeError):
        attach_source_labels([], ["dense"])  # type: ignore[arg-type]
