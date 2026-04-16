"""Lightweight in-memory vector store with SiliconFlow embedding API.

Provides dense retrieval for the eval pipeline (Phase 2).
Embeddings are cached to disk to avoid redundant API calls.
Gracefully degrades when no API key is available.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_MODEL = "BAAI/bge-m3"
EMBEDDING_DIM = 1024


def _extract_text(chunk: dict[str, Any]) -> str:
    return str(chunk.get("content") or chunk.get("claim") or chunk.get("text") or "")


async def _batch_embed(
    texts: list[str],
    api_key: str,
    base_url: str,
    model: str,
    batch_size: int,
) -> list[list[float]]:
    """Embed texts in batches via SiliconFlow API."""
    all_embeddings: list[list[float]] = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            # Skip empty texts
            batch = [t if t.strip() else "empty" for t in batch]
            try:
                resp = await client.post(
                    f"{base_url.rstrip('/')}/embeddings",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "input": batch,
                        "encoding_format": "float",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    batch_embs = [
                        item["embedding"]
                        for item in sorted(data, key=lambda x: x["index"])
                    ]
                    all_embeddings.extend(batch_embs)
                else:
                    logger.warning(
                        "Embedding API %d: %s", resp.status_code, resp.text[:200]
                    )
                    all_embeddings.extend([[0.0] * EMBEDDING_DIM] * len(batch))
            except Exception as e:
                logger.warning("Embedding API error: %s", e)
                all_embeddings.extend([[0.0] * EMBEDDING_DIM] * len(batch))

    return all_embeddings


class ChunkVectorStore:
    """In-memory vector index for chunk-level dense retrieval."""

    def __init__(self, chunks: list[dict[str, Any]], embeddings: np.ndarray):
        self.chunks = chunks
        self._embeddings = embeddings  # (n_chunks, dim)
        self._api_key = os.getenv("SILICONFLOW_API_KEY") or os.getenv(
            "SILICONFLOW_EMBEDDING_API_KEY"
        )
        self._base_url = os.getenv(
            "SILICONFLOW_EMBEDDING_BASE_URL", DEFAULT_BASE_URL
        )
        self._model = os.getenv("SILICONFLOW_EMBEDDING_MODEL", DEFAULT_MODEL)

        # Pre-normalize for fast cosine similarity
        if embeddings.shape[0] > 0:
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)
            self._normed = embeddings / norms
        else:
            self._normed = embeddings

    @property
    def has_embeddings(self) -> bool:
        """True if at least one embedding is non-zero."""
        return bool(self._embeddings.shape[0] > 0 and np.any(self._embeddings != 0))

    @classmethod
    async def build(
        cls,
        chunks: list[dict[str, Any]],
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        cache_path: Path | None = None,
        batch_size: int = 32,
    ) -> ChunkVectorStore:
        """Build index. Uses cached embeddings when available, else calls API."""
        if not chunks:
            return cls([], np.zeros((0, EMBEDDING_DIM), dtype=np.float32))

        n = len(chunks)

        # 1. Try loading from cache
        if cache_path and cache_path.exists():
            try:
                cached = np.load(str(cache_path))
                if cached.shape[0] == n and cached.shape[1] == EMBEDDING_DIM:
                    logger.info("Loaded %d cached embeddings from %s", n, cache_path)
                    return cls(chunks, cached.astype(np.float32))
            except Exception:
                pass

        # 2. Try using pre-computed embeddings from chunk dicts
        pre = [chunk.get("embedding") for chunk in chunks]
        if all(e is not None and len(e) >= EMBEDDING_DIM for e in pre):
            embeddings = np.array(pre, dtype=np.float32)[:, :EMBEDDING_DIM]
            _save_cache(cache_path, embeddings)
            logger.info("Using %d pre-computed embeddings from chunks", n)
            return cls(chunks, embeddings)

        # 3. Compute via API
        resolved_key = api_key or os.getenv("SILICONFLOW_API_KEY") or os.getenv(
            "SILICONFLOW_EMBEDDING_API_KEY"
        )
        resolved_base = os.getenv("SILICONFLOW_EMBEDDING_BASE_URL", base_url)
        resolved_model = os.getenv("SILICONFLOW_EMBEDDING_MODEL", model)

        if not resolved_key:
            logger.warning(
                "No embedding API key available; dense retrieval disabled for %d chunks",
                n,
            )
            return cls(chunks, np.zeros((n, EMBEDDING_DIM), dtype=np.float32))

        texts = [_extract_text(c) for c in chunks]
        logger.info("Embedding %d chunks via API (%s)...", n, resolved_model)
        raw = await _batch_embed(texts, resolved_key, resolved_base, resolved_model, batch_size)
        embeddings = np.array(raw, dtype=np.float32)

        # Validate shape
        if embeddings.shape != (n, EMBEDDING_DIM):
            logger.warning(
                "Embedding shape mismatch: expected (%d, %d), got %s",
                n, EMBEDDING_DIM, embeddings.shape,
            )
            embeddings = np.zeros((n, EMBEDDING_DIM), dtype=np.float32)
        else:
            _save_cache(cache_path, embeddings)

        return cls(chunks, embeddings)

    async def embed_query(self, query_text: str) -> np.ndarray | None:
        """Embed a single query. Returns None if no API key."""
        if not self._api_key or not self.has_embeddings:
            return None
        results = await _batch_embed(
            [query_text], self._api_key, self._base_url, self._model, batch_size=1
        )
        if results and len(results[0]) >= EMBEDDING_DIM:
            return np.array(results[0][:EMBEDDING_DIM], dtype=np.float32)
        return None

    async def batch_embed_queries(
        self, texts: list[str], batch_size: int = 32
    ) -> list[np.ndarray | None]:
        """Embed multiple queries in batch. Returns list parallel to *texts*."""
        if not self._api_key or not self.has_embeddings or not texts:
            return [None] * len(texts)
        raw = await _batch_embed(
            texts, self._api_key, self._base_url, self._model, batch_size
        )
        out: list[np.ndarray | None] = []
        for vec in raw:
            if vec and len(vec) >= EMBEDDING_DIM:
                out.append(np.array(vec[:EMBEDDING_DIM], dtype=np.float32))
            else:
                out.append(None)
        return out

    def cosine_search(self, query_vec: np.ndarray, top_k: int = 10) -> list[dict[str, Any]]:
        """Find top_k most similar chunks by cosine similarity."""
        if self._embeddings.shape[0] == 0 or query_vec is None:
            return []
        q_norm = np.linalg.norm(query_vec)
        if q_norm == 0:
            return []
        q_normed = query_vec / q_norm

        scores = self._normed @ q_normed  # (n_chunks,)
        top_indices = np.argsort(scores)[::-1][:top_k]

        results: list[dict[str, Any]] = []
        for idx in top_indices:
            if scores[idx] <= 0:
                continue
            item = dict(self.chunks[int(idx)])
            item["dense_score"] = round(float(scores[idx]), 4)
            results.append(item)
        return results

    def cosine_search_vec(
        self, query_vec: np.ndarray, chunk_indices: list[int] | None = None
    ) -> dict[int, float]:
        """Return cosine scores as {chunk_index: score} for use by hybrid retriever."""
        if self._embeddings.shape[0] == 0 or query_vec is None:
            return {}
        q_norm = np.linalg.norm(query_vec)
        if q_norm == 0:
            return {}
        q_normed = query_vec / q_norm
        scores = self._normed @ q_normed

        indices = chunk_indices if chunk_indices is not None else range(len(scores))
        return {int(i): float(scores[i]) for i in indices}


def _save_cache(cache_path: Path | None, embeddings: np.ndarray) -> None:
    if cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            np.save(str(cache_path), embeddings)
            logger.info("Saved embedding cache to %s", cache_path)
        except Exception as e:
            logger.warning("Failed to save embedding cache: %s", e)
