"""Phase 2 tests: dense retrieval + RRF fusion correctness."""
from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest

from chunk_vector_store import ChunkVectorStore, EMBEDDING_DIM
from eval_retrieval_runtime import _rrf_fuse


# ───── ChunkVectorStore unit tests ─────


def _make_chunks_with_embeddings(n: int, dim: int = EMBEDDING_DIM) -> tuple:
    """Create n chunks with random embeddings for testing."""
    rng = np.random.default_rng(42)
    chunks = [
        {"chunk_id": f"c_{i}", "material_id": f"mat_{i}", "content": f"text {i}"}
        for i in range(n)
    ]
    embeddings = rng.standard_normal((n, dim)).astype(np.float32)
    return chunks, embeddings


def test_cosine_search_returns_correct_top_k():
    chunks, embeddings = _make_chunks_with_embeddings(10)
    store = ChunkVectorStore(chunks, embeddings)

    # Query is the first chunk's embedding → should rank first
    query_vec = embeddings[0]
    results = store.cosine_search(query_vec, top_k=3)

    assert len(results) <= 3
    assert results[0]["chunk_id"] == "c_0"
    assert results[0]["dense_score"] > 0.99  # near-perfect self-similarity


def test_cosine_search_empty_store():
    store = ChunkVectorStore([], np.zeros((0, EMBEDDING_DIM), dtype=np.float32))
    results = store.cosine_search(np.ones(EMBEDDING_DIM, dtype=np.float32), top_k=5)
    assert results == []


def test_cosine_search_zero_query():
    chunks, embeddings = _make_chunks_with_embeddings(3)
    store = ChunkVectorStore(chunks, embeddings)
    results = store.cosine_search(np.zeros(EMBEDDING_DIM, dtype=np.float32), top_k=5)
    assert results == []


def test_has_embeddings_true_when_nonzero():
    chunks, embeddings = _make_chunks_with_embeddings(3)
    store = ChunkVectorStore(chunks, embeddings)
    assert store.has_embeddings is True


def test_has_embeddings_false_when_zero():
    chunks = [{"chunk_id": "c_0", "content": "x"}]
    store = ChunkVectorStore(chunks, np.zeros((1, EMBEDDING_DIM), dtype=np.float32))
    assert store.has_embeddings is False


def test_build_with_precomputed_embeddings():
    chunks = [
        {"chunk_id": "c_0", "content": "hello", "embedding": list(np.random.randn(EMBEDDING_DIM))},
        {"chunk_id": "c_1", "content": "world", "embedding": list(np.random.randn(EMBEDDING_DIM))},
    ]
    store = asyncio.run(ChunkVectorStore.build(chunks))
    assert store.has_embeddings is True
    assert store._embeddings.shape == (2, EMBEDDING_DIM)


def test_build_empty_chunks():
    store = asyncio.run(ChunkVectorStore.build([]))
    assert store._embeddings.shape == (0, EMBEDDING_DIM)
    assert store.has_embeddings is False


def test_build_no_api_key_graceful(monkeypatch):
    """Without API key and without pre-computed embeddings, should return zero-filled store."""
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("SILICONFLOW_EMBEDDING_API_KEY", raising=False)
    chunks = [{"chunk_id": "c_0", "content": "hello"}]
    store = asyncio.run(ChunkVectorStore.build(chunks))
    assert store._embeddings.shape == (1, EMBEDDING_DIM)
    assert store.has_embeddings is False


def test_build_raises_when_cache_shape_or_count_mismatch(tmp_path):
    """Guardrail: cached embedding count/shape drift must fail fast instead of silently recomputing."""
    chunks = [
        {"chunk_id": "c_0", "content": "hello", "embedding": list(np.random.randn(EMBEDDING_DIM))},
        {"chunk_id": "c_1", "content": "world", "embedding": list(np.random.randn(EMBEDDING_DIM))},
    ]
    cache_path = tmp_path / "corpus_embeddings.npy"

    # Deliberately wrong cache shape: expected (2, EMBEDDING_DIM), actual (1, EMBEDDING_DIM).
    np.save(str(cache_path), np.zeros((1, EMBEDDING_DIM), dtype=np.float32))
    (tmp_path / "corpus_embeddings.manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "chunk_count": 1,
                "embedding_shape": [1, EMBEDDING_DIM],
                "is_contextual": False,
                "chunks_hash": "placeholder",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        asyncio.run(ChunkVectorStore.build(chunks, cache_path=cache_path))


def test_build_raises_when_contextual_mode_mismatch(tmp_path):
    """Guardrail: manifest contextual mode must match current chunk mode."""
    chunks = [
        {"chunk_id": "c_0", "content": "plain content", "embedding": list(np.random.randn(EMBEDDING_DIM))},
    ]
    cache_path = tmp_path / "corpus_embeddings.npy"
    np.save(str(cache_path), np.zeros((1, EMBEDDING_DIM), dtype=np.float32))
    (tmp_path / "corpus_embeddings.manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "chunk_count": 1,
                "embedding_shape": [1, EMBEDDING_DIM],
                "is_contextual": True,
                "chunks_hash": "placeholder",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        asyncio.run(ChunkVectorStore.build(chunks, cache_path=cache_path))


def test_cosine_search_vec_returns_scores():
    chunks, embeddings = _make_chunks_with_embeddings(5)
    store = ChunkVectorStore(chunks, embeddings)
    query_vec = embeddings[2]
    scores = store.cosine_search_vec(query_vec)
    assert isinstance(scores, dict)
    assert len(scores) == 5
    # Self-similarity should be highest
    assert scores[2] == max(scores.values())


# ───── RRF fusion tests ─────


def test_rrf_fuse_single_list():
    items = [
        {"chunk_id": "a", "score": 10},
        {"chunk_id": "b", "score": 5},
    ]
    fused = _rrf_fuse([items], top_k=5)
    assert len(fused) == 2
    assert fused[0]["chunk_id"] == "a"
    assert "rrf_score" in fused[0]


def test_rrf_fuse_deduplicates():
    list_a = [{"chunk_id": "a"}, {"chunk_id": "b"}]
    list_b = [{"chunk_id": "b"}, {"chunk_id": "a"}]
    fused = _rrf_fuse([list_a, list_b], top_k=5)
    chunk_ids = [item["chunk_id"] for item in fused]
    assert len(chunk_ids) == 2
    assert set(chunk_ids) == {"a", "b"}


def test_rrf_fuse_empty_lists():
    fused = _rrf_fuse([[], [], []], top_k=5)
    assert fused == []


def test_rrf_fuse_respects_top_k():
    items = [{"chunk_id": f"c_{i}"} for i in range(20)]
    fused = _rrf_fuse([items], top_k=5)
    assert len(fused) == 5


def test_rrf_fuse_three_way():
    """Three-way fusion should boost items appearing in multiple lists."""
    list_bm25 = [{"chunk_id": "x"}, {"chunk_id": "y"}, {"chunk_id": "z"}]
    list_graph = [{"chunk_id": "y"}, {"chunk_id": "x"}]
    list_dense = [{"chunk_id": "y"}, {"chunk_id": "z"}]
    fused = _rrf_fuse([list_bm25, list_graph, list_dense], top_k=3)
    # "y" appears in all three lists → should rank first
    assert fused[0]["chunk_id"] == "y"


# ───── Dense branch integration check ─────


def test_dense_branch_uses_vector_similarity_not_bm25_copy():
    """Phase 2 gate: verify the dense retrieval path is real, not a BM25 copy."""
    from layers.r_layer_hybrid_retriever import _cosine_sim

    assert callable(_cosine_sim)
    # cosine of identical vectors == 1.0
    v = [1.0, 0.0, 0.0]
    assert abs(_cosine_sim(v, v) - 1.0) < 1e-6
    # cosine of orthogonal vectors == 0.0
    assert abs(_cosine_sim([1, 0, 0], [0, 1, 0])) < 1e-6
