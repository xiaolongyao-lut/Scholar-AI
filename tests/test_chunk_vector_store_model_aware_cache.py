"""P2 L2 regression: embedding cache invalidation on model switch.

Verifies that switching embedding model yields distinct cache artifacts.
"""

import json
import tempfile
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

from chunk_vector_store import ChunkVectorStore, _compute_model_hash


@pytest.mark.asyncio
async def test_two_models_build_two_independent_caches():
    """Mock two models, build twice, assert two independent cache artifacts."""
    chunks = [
        {"chunk_id": "c1", "content": "first chunk text"},
        {"chunk_id": "c2", "content": "second chunk text"},
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        # Build with model A
        cache_base_a = Path(tmpdir) / "model_a_cache.npy"

        with mock.patch(
            "chunk_vector_store._invoke_embedding_http",
            return_value=[0.1] * 1024,
        ):
            store_a = await ChunkVectorStore.build(
                chunks,
                api_key="fake_key",
                model="model-A-8B",
                cache_path=cache_base_a,
            )

        # Compute expected cache path for model A
        hash_a = _compute_model_hash("model-A-8B", 1024)
        expected_cache_a = Path(tmpdir) / f"model_a_cache_m{hash_a}.npy"
        
        # Verify model A cache exists
        assert expected_cache_a.exists()
        manifest_a_path = expected_cache_a.with_suffix(".manifest.json")
        assert manifest_a_path.exists()
        manifest_a = json.loads(manifest_a_path.read_text(encoding="utf-8"))

        # Build with model B — should create distinct cache
        cache_base_b = Path(tmpdir) / "model_b_cache.npy"

        with mock.patch(
            "chunk_vector_store._invoke_embedding_http",
            return_value=[0.2] * 1024,
        ):
            store_b = await ChunkVectorStore.build(
                chunks,
                api_key="fake_key",
                model="model-B-12B",
                cache_path=cache_base_b,
            )

        # Compute expected cache path for model B
        hash_b = _compute_model_hash("model-B-12B", 1024)
        expected_cache_b = Path(tmpdir) / f"model_b_cache_m{hash_b}.npy"
        
        # Verify model B cache exists and is distinct
        assert expected_cache_b.exists()
        manifest_b_path = expected_cache_b.with_suffix(".manifest.json")
        assert manifest_b_path.exists()
        manifest_b = json.loads(manifest_b_path.read_text(encoding="utf-8"))

        # Two distinct caches should exist
        assert expected_cache_a.exists()
        assert expected_cache_b.exists()
        assert expected_cache_a != expected_cache_b

        # Embeddings should differ
        embeddings_a = np.load(str(expected_cache_a))
        embeddings_b = np.load(str(expected_cache_b))
        assert not np.allclose(embeddings_a, embeddings_b)


@pytest.mark.asyncio
async def test_cache_miss_on_model_switch_same_base_path():
    """When using same base cache path, model switch should create distinct artifact."""
    chunks = [{"chunk_id": "c1", "content": "test chunk"}]

    with tempfile.TemporaryDirectory() as tmpdir:
        base_path = Path(tmpdir) / "embeddings.npy"

        # First build with model A
        with mock.patch(
            "chunk_vector_store._invoke_embedding_http",
            return_value=[0.1] * 1024,
        ):
            store_a = await ChunkVectorStore.build(
                chunks,
                api_key="fake_key",
                model="model-A",
                cache_path=base_path,
            )

        # Check what cache file was actually created
        cache_files_after_a = list(Path(tmpdir).glob("*.npy"))
        assert len(cache_files_after_a) == 1
        actual_cache_a = cache_files_after_a[0]

        # Second build with model B using same base path
        with mock.patch(
            "chunk_vector_store._invoke_embedding_http",
            return_value=[0.2] * 1024,
        ):
            store_b = await ChunkVectorStore.build(
                chunks,
                api_key="fake_key",
                model="model-B",
                cache_path=base_path,
            )

        # Should now have two distinct cache files
        cache_files_after_b = list(Path(tmpdir).glob("*.npy"))
        assert len(cache_files_after_b) == 2

        # Both models' caches should coexist
        assert actual_cache_a.exists()


@pytest.mark.asyncio
async def test_cache_hit_on_same_model_rebuild():
    """Rebuilding with same model should hit cache (not invoke API)."""
    chunks = [{"chunk_id": "c1", "content": "test chunk"}]

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_base = Path(tmpdir) / "test_cache.npy"

        # First build
        with mock.patch(
            "chunk_vector_store.gated_call",
            side_effect=lambda **kwargs: [0.5] * 1024,
        ) as mock_gateway:
            store_1 = await ChunkVectorStore.build(
                chunks,
                api_key="fake_key",
                model="model-X",
                cache_path=cache_base,
            )
            first_call_count = mock_gateway.call_count

        # Verify cache was created
        hash_x = _compute_model_hash("model-X", 1024)
        expected_cache = Path(tmpdir) / f"test_cache_m{hash_x}.npy"
        assert expected_cache.exists()

        # Second build with same model — should hit cache
        with mock.patch(
            "chunk_vector_store.gated_call",
            side_effect=lambda **kwargs: [0.5] * 1024,
        ) as mock_gateway_2:
            store_2 = await ChunkVectorStore.build(
                chunks,
                api_key="fake_key",
                model="model-X",
                cache_path=cache_base,
            )
            second_call_count = mock_gateway_2.call_count

        # API should be called on first build but not on second (cache hit)
        assert first_call_count > 0
        assert second_call_count == 0


@pytest.mark.asyncio
async def test_build_preserves_bge_model_for_query_embedding_consistency() -> None:
    """Store model must stay aligned with corpus embedding model."""
    chunks = [{"chunk_id": "c1", "content": "test chunk", "embedding": [0.1] * 1024}]

    store = await ChunkVectorStore.build(
        chunks,
        api_key="fake_key",
        model="BAAI/bge-m3",
    )

    assert store._model == "BAAI/bge-m3"
