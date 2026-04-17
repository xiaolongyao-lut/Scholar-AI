"""Lightweight in-memory vector store with SiliconFlow embedding API.

Provides dense retrieval for the eval pipeline (Phase 2).
Embeddings are cached to disk to avoid redundant API calls.
Gracefully degrades when no API key is available.
"""

from __future__ import annotations

import hashlib
import json
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
MANIFEST_VERSION = 1


def _extract_text(chunk: dict[str, Any]) -> str:
    return str(chunk.get("content") or chunk.get("claim") or chunk.get("text") or "")


def _is_contextualized_chunk(chunk: dict[str, Any]) -> bool:
    content = str(chunk.get("content") or "").lstrip()
    return bool(content.startswith("[") and "]" in content[:300])


def _resolve_effective_cache_path(cache_path: Path | None, chunks: list[dict[str, Any]]) -> Path | None:
    if cache_path is None:
        return None
    if any(_is_contextualized_chunk(chunk) for chunk in chunks):
        return cache_path.with_name(f"{cache_path.stem}_contextual{cache_path.suffix}")
    return cache_path


def _cache_manifest_path(cache_path: Path) -> Path:
    return cache_path.with_suffix(".manifest.json")


def _chunks_hash(chunks: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        payload = json.dumps(chunk, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest.update(payload.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _build_manifest(chunks: list[dict[str, Any]], embeddings: np.ndarray) -> dict[str, Any]:
    return {
        "version": MANIFEST_VERSION,
        "chunk_count": len(chunks),
        "chunks_hash": _chunks_hash(chunks),
        "embedding_shape": [int(embeddings.shape[0]), int(embeddings.shape[1])],
        "embedding_dim": EMBEDDING_DIM,
        "is_contextual": any(_is_contextualized_chunk(chunk) for chunk in chunks),
    }


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        raise ValueError(f"Embedding cache manifest missing: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive parse failure
        raise ValueError(f"Embedding cache manifest unreadable: {manifest_path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Embedding cache manifest invalid format: {manifest_path}")
    return payload


def _validate_cache_guard(
    *,
    chunks: list[dict[str, Any]],
    cached: np.ndarray,
    manifest: dict[str, Any],
    cache_path: Path,
) -> None:
    expected_count = len(chunks)
    expected_shape = (expected_count, EMBEDDING_DIM)
    if cached.shape != expected_shape:
        raise ValueError(
            f"Embedding cache shape mismatch at {cache_path}: expected {expected_shape}, got {cached.shape}"
        )

    chunk_count = manifest.get("chunk_count")
    if not isinstance(chunk_count, int) or chunk_count != expected_count:
        raise ValueError(
            f"Embedding cache manifest chunk_count mismatch at {cache_path}: expected {expected_count}, got {chunk_count}"
        )

    manifest_shape = manifest.get("embedding_shape")
    if (
        not isinstance(manifest_shape, list)
        or len(manifest_shape) != 2
        or int(manifest_shape[0]) != expected_shape[0]
        or int(manifest_shape[1]) != expected_shape[1]
    ):
        raise ValueError(
            f"Embedding cache manifest shape mismatch at {cache_path}: expected {list(expected_shape)}, got {manifest_shape}"
        )

    manifest_dim = manifest.get("embedding_dim")
    if manifest_dim is not None and int(manifest_dim) != EMBEDDING_DIM:
        raise ValueError(
            f"Embedding cache manifest dimension mismatch at {cache_path}: expected {EMBEDDING_DIM}, got {manifest_dim}"
        )

    expected_contextual = any(_is_contextualized_chunk(chunk) for chunk in chunks)
    manifest_contextual = manifest.get("is_contextual")
    if not isinstance(manifest_contextual, bool) or manifest_contextual != expected_contextual:
        raise ValueError(
            f"Embedding cache manifest contextual-mode mismatch at {cache_path}: "
            f"expected {expected_contextual}, got {manifest_contextual}"
        )

    expected_hash = _chunks_hash(chunks)
    manifest_hash = manifest.get("chunks_hash")
    if not isinstance(manifest_hash, str) or manifest_hash != expected_hash:
        raise ValueError(
            f"Embedding cache manifest chunks_hash mismatch at {cache_path}: "
            "corpus changed while cache remained stale"
        )


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
        strict_cache_guard: bool = True,
    ) -> ChunkVectorStore:
        """Build index. Uses cached embeddings when available, else calls API."""
        if not chunks:
            return cls([], np.zeros((0, EMBEDDING_DIM), dtype=np.float32))

        n = len(chunks)
        effective_cache_path = _resolve_effective_cache_path(cache_path, chunks)

        # 1. Try loading from cache
        if effective_cache_path and effective_cache_path.exists():
            if strict_cache_guard:
                manifest = _load_manifest(_cache_manifest_path(effective_cache_path))
                cached = np.load(str(effective_cache_path))
                _validate_cache_guard(
                    chunks=chunks,
                    cached=cached,
                    manifest=manifest,
                    cache_path=effective_cache_path,
                )
                logger.info("Loaded %d cached embeddings from %s (manifest-verified)", n, effective_cache_path)
                return cls(chunks, cached.astype(np.float32))

            try:
                cached = np.load(str(effective_cache_path))
                if cached.shape[0] == n and cached.shape[1] == EMBEDDING_DIM:
                    logger.info("Loaded %d cached embeddings from %s", n, effective_cache_path)
                    return cls(chunks, cached.astype(np.float32))
            except Exception:
                pass

        # 2. Try using pre-computed embeddings from chunk dicts
        pre = [chunk.get("embedding") for chunk in chunks]
        if all(e is not None and len(e) >= EMBEDDING_DIM for e in pre):
            embeddings = np.array(pre, dtype=np.float32)[:, :EMBEDDING_DIM]
            _save_cache(effective_cache_path, embeddings, chunks)
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
            _save_cache(effective_cache_path, embeddings, chunks)

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


def _save_cache(cache_path: Path | None, embeddings: np.ndarray, chunks: list[dict[str, Any]]) -> None:
    if cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            np.save(str(cache_path), embeddings)
            manifest = _build_manifest(chunks, embeddings)
            _cache_manifest_path(cache_path).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("Saved embedding cache to %s", cache_path)
        except Exception as e:
            logger.warning("Failed to save embedding cache: %s", e)
