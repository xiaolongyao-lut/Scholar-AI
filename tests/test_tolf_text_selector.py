from __future__ import annotations

import numpy as np
import pytest

from tolf_text_selector import make_local_text_embeddings, select_tolf_context_chunks


def test_local_text_embeddings_are_deterministic_and_normalized() -> None:
    texts = [
        "Laser power increased hardness to 280 HV.",
        "Cooling rate changed microstructure.",
    ]

    first = make_local_text_embeddings(texts, dim=32)
    second = make_local_text_embeddings(texts, dim=32)

    assert first.shape == (2, 32)
    assert np.allclose(first, second)
    assert np.all(np.linalg.norm(first, axis=1) <= 1.0001)


def test_select_tolf_context_chunks_preserves_provenance() -> None:
    chunks = [
        {
            "chunk_id": "c_result",
            "material_id": "mat_result",
            "title": "Laser Result Paper",
            "content": "This study reports laser power increased hardness to 280 HV.",
            "source_labels": ["project_chunks"],
        },
        {
            "chunk_id": "c_noise",
            "material_id": "mat_noise",
            "title": "Botany Paper",
            "content": "Urban trees and rainfall were observed in autumn parks.",
            "source_labels": ["project_chunks"],
        },
    ]

    selected = select_tolf_context_chunks(
        "laser power hardness",
        chunks,
        top_k=1,
        embedding_dim=16,
        max_candidates=2,
    )

    assert len(selected) == 1
    assert selected[0]["chunk_id"] == "c_result"
    assert selected[0]["material_id"] == "mat_result"
    assert selected[0]["tolf_rank"] == 1
    assert selected[0]["tolf_activation_score"] > 0
    assert "tolf_text_selector" in selected[0]["source_labels"]
    assert selected[0]["query_overlap_tokens"] == ["hardness", "laser", "power"]


def test_select_tolf_context_chunks_rejects_invalid_contracts() -> None:
    with pytest.raises(ValueError, match="query must be a non-empty string"):
        select_tolf_context_chunks("", [], top_k=1)

    with pytest.raises(ValueError, match="top_k must be a positive integer"):
        select_tolf_context_chunks("laser", [], top_k=0)

    with pytest.raises(TypeError, match="chunks must be a sequence"):
        select_tolf_context_chunks("laser", "not chunks", top_k=1)  # type: ignore[arg-type]


def test_select_tolf_context_chunks_boosts_lexical_overlap() -> None:
    chunks = [
        {
            "chunk_id": "c_overlap",
            "material_id": "mat_overlap",
            "title": "Laser Welding Paper",
            "content": "Laser welding power optimization increased hardness to 300 HV.",
            "source_labels": ["project_chunks"],
        },
        {
            "chunk_id": "c_semantic",
            "material_id": "mat_semantic",
            "title": "Beam Joining Paper",
            "content": "High-energy beam joining process improved mechanical properties significantly.",
            "source_labels": ["project_chunks"],
        },
    ]

    selected = select_tolf_context_chunks(
        "laser welding power hardness",
        chunks,
        top_k=2,
        embedding_dim=16,
        max_candidates=2,
    )

    assert len(selected) >= 1
    top_chunk = selected[0]
    assert top_chunk["chunk_id"] == "c_overlap"
    assert len(top_chunk["query_overlap_tokens"]) >= 3
    assert "laser" in top_chunk["query_overlap_tokens"]
    assert "welding" in top_chunk["query_overlap_tokens"]
    assert "power" in top_chunk["query_overlap_tokens"]
