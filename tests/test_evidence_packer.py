from __future__ import annotations

import evidence_packer


def _candidate(
    chunk_id: str,
    material_id: str,
    score: float,
    text: str,
) -> dict:
    return {
        "chunk_id": chunk_id,
        "material_id": material_id,
        "score": score,
        "text": text,
    }


def _patch_token_cost(monkeypatch, token_map: dict[str, int]) -> None:
    monkeypatch.setattr(
        evidence_packer,
        "count_tokens",
        lambda rendered: token_map[rendered.rsplit(" ", 1)[-1]],
    )


def test_pack_evidence_enforces_per_material_cap(monkeypatch) -> None:
    monkeypatch.setattr(evidence_packer, "count_tokens", lambda _: 200)
    candidates = [
        _candidate(f"a-{index}", "paper-a", 1.0 - index * 0.01, f"paper a chunk {index}")
        for index in range(6)
    ] + [
        _candidate(f"b-{index}", f"paper-{index}", 0.7 - index * 0.01, f"other chunk {index}")
        for index in range(4)
    ]

    packed = evidence_packer.pack_evidence(
        candidates,
        budget_tokens=4000,
        hard_cap_tokens=5000,
        max_per_material=2,
        top_k=10,
    )

    assert sum(1 for item in packed if item["material_id"] == "paper-a") == 2


def test_pack_evidence_skips_single_candidate_above_budget_and_keeps_next(monkeypatch) -> None:
    token_map = {
        "oversized": 4500,
        "fits-1": 1200,
        "fits-2": 1000,
    }
    _patch_token_cost(monkeypatch, token_map)
    candidates = [
        _candidate("c-oversized", "paper-a", 0.99, "oversized"),
        _candidate("c-fit-1", "paper-b", 0.95, "fits-1"),
        _candidate("c-fit-2", "paper-c", 0.90, "fits-2"),
    ]

    packed = evidence_packer.pack_evidence(
        candidates,
        budget_tokens=4000,
        hard_cap_tokens=5000,
        max_per_material=2,
        top_k=3,
    )

    assert [item["chunk_id"] for item in packed] == ["c-fit-1", "c-fit-2"]


def test_pack_evidence_trims_low_score_tail_to_hard_cap(monkeypatch) -> None:
    token_map = {
        "chunk-1": 2200,
        "chunk-2": 2100,
        "chunk-3": 1600,
    }
    _patch_token_cost(monkeypatch, token_map)
    candidates = [
        _candidate("c-1", "paper-a", 0.99, "chunk-1"),
        _candidate("c-2", "paper-b", 0.95, "chunk-2"),
        _candidate("c-3", "paper-c", 0.90, "chunk-3"),
    ]

    packed = evidence_packer.pack_evidence(
        candidates,
        budget_tokens=4000,
        hard_cap_tokens=5000,
        max_per_material=2,
        top_k=3,
    )

    assert [item["chunk_id"] for item in packed] == ["c-1", "c-2"]
    assert sum(token_map[item["text"]] for item in packed) <= 5000


def test_pack_evidence_applies_hard_jaccard_dedupe_before_budget_trim(monkeypatch) -> None:
    monkeypatch.setattr(evidence_packer, "count_tokens", lambda _: 300)
    candidates = [
        _candidate("c-1", "paper-a", 0.99, "alpha beta gamma delta"),
        _candidate("c-2", "paper-a", 0.95, "alpha beta gamma delta"),
        _candidate("c-3", "paper-b", 0.90, "distinct evidence"),
    ]

    packed = evidence_packer.pack_evidence(
        candidates,
        budget_tokens=4000,
        hard_cap_tokens=5000,
        max_per_material=2,
        top_k=3,
    )

    assert [item["chunk_id"] for item in packed] == ["c-1", "c-3"]


def test_pack_evidence_drops_same_material_redundancy_only_when_above_soft_budget(monkeypatch) -> None:
    token_map = {
        "primary": 2200,
        "redundant": 2100,
        "other": 500,
    }
    _patch_token_cost(monkeypatch, token_map)
    candidates = [
        _candidate("c-1", "paper-a", 0.99, "primary"),
        _candidate("c-2", "paper-a", 0.95, "redundant"),
        _candidate("c-3", "paper-b", 0.90, "other"),
    ]
    monkeypatch.setattr(
        evidence_packer,
        "_jaccard_similarity",
        lambda left, right: 0.8 if {left, right} == {"primary", "redundant"} else 0.0,
    )

    packed = evidence_packer.pack_evidence(
        candidates,
        budget_tokens=4000,
        hard_cap_tokens=5000,
        max_per_material=2,
        top_k=3,
    )

    assert [item["chunk_id"] for item in packed] == ["c-1", "c-3"]


def test_pack_evidence_preserves_score_order_among_retained_items(monkeypatch) -> None:
    monkeypatch.setattr(evidence_packer, "count_tokens", lambda _: 600)
    candidates = [
        _candidate("c-1", "paper-a", 0.98, "first"),
        _candidate("c-2", "paper-a", 0.97, "second"),
        _candidate("c-3", "paper-a", 0.96, "third"),
        _candidate("c-4", "paper-b", 0.95, "fourth"),
    ]

    packed = evidence_packer.pack_evidence(
        candidates,
        budget_tokens=4000,
        hard_cap_tokens=5000,
        max_per_material=2,
        top_k=4,
    )

    assert [item["chunk_id"] for item in packed] == ["c-1", "c-2", "c-4"]


def test_build_evidence_reference_preserves_compression_provenance() -> None:
    candidate = {
        "chunk_id": "chunk-1",
        "material_id": "paper-a",
        "score": "0.875",
        "page": "12",
        "source": "local_file",
        "source_labels": ["dense", "rerank"],
        "source_hint": "dense+rerank",
        "label": "highly_relevant",
        "quote": "Beam power correlates with penetration depth.",
        "compressed_text": "Beam power -> penetration depth.",
        "text": "Full source text that remains available for audit.",
    }

    reference = evidence_packer.build_evidence_reference(candidate)

    assert reference == {
        "chunk_id": "chunk-1",
        "material_id": "paper-a",
        "text": "Full source text that remains available for audit.",
        "compressed_text": "Beam power -> penetration depth.",
        "quote": "Beam power correlates with penetration depth.",
        "label": "highly_relevant",
        "score": 0.875,
        "page": 12,
        "source": "local_file",
        "source_label": "dense+rerank",
        "source_hint": "dense+rerank",
        "source_labels": ["dense", "rerank"],
    }


def test_format_evidence_item_renders_source_labels_without_losing_quote() -> None:
    rendered = evidence_packer.format_evidence_item(
        {
            "chunk_id": "chunk-1",
            "material_id": "paper-a",
            "score": 0.91,
            "source_labels": ["bm25", "rrf"],
            "quote": "traceable quote",
            "compressed_text": "compressed context",
        }
    )

    assert "SOURCE_ID: [chunk-1]" in rendered
    assert "SOURCE_LABELS: bm25, rrf" in rendered
    assert "QUOTE: traceable quote" in rendered
    assert "BODY: compressed context" in rendered


def test_build_evidence_reference_uses_source_text_fallback() -> None:
    reference = evidence_packer.build_evidence_reference(
        {
            "chunk_id": "chunk-1",
            "material_id": "paper-a",
            "source_text": "Source text from local fallback.",
        }
    )

    assert reference["text"] == "Source text from local fallback."
