"""Lightweight in-memory vector store with SiliconFlow embedding API.

Provides dense retrieval for the eval pipeline (Phase 2).
Embeddings are cached to disk to avoid redundant API calls.
Gracefully degrades when no API key is available.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from token_utils import count_tokens, split_by_tokens

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_MODEL = "Qwen/Qwen3-Embedding-8B"
EMBEDDING_DIM = 1024
MANIFEST_VERSION = 1

SAFE_EMBED_TOKENS = 7500  # headroom under SiliconFlow /embeddings 8192-token cap
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_EMBED_RETRIES = 3
BASE_EMBED_BACKOFF = 0.5
MAX_EMBED_BACKOFF = 30.0


class EmbeddingAPIError(RuntimeError):
    """Raised when the embedding API cannot produce a usable vector."""


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
    zero_rows = int(np.sum((embeddings == 0).all(axis=1))) if embeddings.shape[0] > 0 else 0
    return {
        "version": MANIFEST_VERSION,
        "chunk_count": len(chunks),
        "chunks_hash": _chunks_hash(chunks),
        "embedding_shape": [int(embeddings.shape[0]), int(embeddings.shape[1])],
        "embedding_dim": EMBEDDING_DIM,
        "is_contextual": any(_is_contextualized_chunk(chunk) for chunk in chunks),
        "zero_row_count": zero_rows,
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


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        return vec
    return vec / norm


def _compute_embed_backoff(attempt: int) -> float:
    delay = min(BASE_EMBED_BACKOFF * (2 ** attempt), MAX_EMBED_BACKOFF)
    return delay + random.uniform(0.0, delay)


async def _post_embed_batch(
    client: httpx.AsyncClient,
    batch: list[str],
    api_key: str,
    base_url: str,
    model: str,
) -> list[list[float]]:
    """POST one batch of texts to /embeddings with retry. Raises on failure."""
    payload = {
        "model": model,
        "input": batch,
        "encoding_format": "float",
        "dimensions": EMBEDDING_DIM,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_status: int | None = None
    last_body: str = ""
    for attempt in range(MAX_EMBED_RETRIES):
        try:
            resp = await client.post(
                f"{base_url.rstrip('/')}/embeddings",
                headers=headers,
                json=payload,
            )
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.TimeoutException) as exc:
            if attempt < MAX_EMBED_RETRIES - 1:
                await asyncio.sleep(_compute_embed_backoff(attempt))
                continue
            raise EmbeddingAPIError(f"embedding transport error: {exc}") from exc

        if resp.status_code == 200:
            data = resp.json().get("data", []) or []
            return [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]

        last_status = resp.status_code
        last_body = (resp.text or "")[:240]

        if resp.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_EMBED_RETRIES - 1:
            await asyncio.sleep(_compute_embed_backoff(attempt))
            continue

        # Non-retryable (400/413/404/401/...). Report loudly — no silent zero fallback.
        break

    raise EmbeddingAPIError(
        f"embedding API failed after {MAX_EMBED_RETRIES} attempts "
        f"(last_status={last_status}, body={last_body!r}); "
        f"batch_size={len(batch)}, first_preview={batch[0][:80]!r}"
    )


async def _embed_single_long(
    text: str,
    api_key: str,
    base_url: str,
    model: str,
    client: httpx.AsyncClient,
) -> list[float]:
    """Split an oversized text, embed each piece, L2-mean-pool back to one vector."""
    pieces = split_by_tokens(text, SAFE_EMBED_TOKENS)
    if not pieces:
        raise EmbeddingAPIError("split_by_tokens produced 0 pieces for non-empty input")
    logger.info(
        "embed: single text %d tokens split into %d piece(s) for mean-pool",
        count_tokens(text),
        len(pieces),
    )
    # Re-check: every piece must be under the API limit after splitting.
    for idx, piece in enumerate(pieces):
        piece_tokens = count_tokens(piece)
        if piece_tokens > SAFE_EMBED_TOKENS:
            raise EmbeddingAPIError(
                f"after split guard, piece #{idx} still {piece_tokens} > {SAFE_EMBED_TOKENS}; "
                "investigate token_utils.split_by_tokens"
            )
    sub_raw = await _post_embed_batch(client, pieces, api_key, base_url, model)
    sub_arr = np.array(sub_raw, dtype=np.float32)
    normed = np.stack([_l2_normalize(row) for row in sub_arr], axis=0)
    pooled = _l2_normalize(normed.mean(axis=0))
    return pooled.tolist()


async def _batch_embed(
    texts: list[str],
    api_key: str,
    base_url: str,
    model: str,
    batch_size: int,
) -> list[list[float]]:
    """Embed texts with token-aware split+mean-pool for oversized entries.

    Raises `EmbeddingAPIError` on transport/HTTP failures — no silent zero fallback.
    """
    if not texts:
        return []

    # Normalize empty → "empty" placeholder (preserves historical behavior).
    normalized = [t if (t and t.strip()) else "empty" for t in texts]

    # Pre-check token lengths; tag long ones for split+mean-pool.
    lengths = [count_tokens(t) for t in normalized]
    long_slots = {i for i, n in enumerate(lengths) if n > SAFE_EMBED_TOKENS}

    if long_slots:
        logger.info(
            "embed: %d/%d texts exceed SAFE_EMBED_TOKENS=%d; routing through split+mean-pool",
            len(long_slots),
            len(normalized),
            SAFE_EMBED_TOKENS,
        )

    output: list[list[float] | None] = [None] * len(normalized)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1) Fill long slots via split+mean-pool (one text at a time).
        for i in sorted(long_slots):
            output[i] = await _embed_single_long(normalized[i], api_key, base_url, model, client)

        # 2) Batch-embed the rest.
        regular_indices = [i for i in range(len(normalized)) if i not in long_slots]
        for start in range(0, len(regular_indices), batch_size):
            window = regular_indices[start : start + batch_size]
            batch_texts = [normalized[i] for i in window]
            sub_raw = await _post_embed_batch(client, batch_texts, api_key, base_url, model)
            if len(sub_raw) != len(window):
                raise EmbeddingAPIError(
                    f"embedding API returned {len(sub_raw)} vectors for {len(window)} inputs"
                )
            for slot_idx, vec in zip(window, sub_raw):
                output[slot_idx] = vec

    # Final sanity: every slot filled.
    missing = [i for i, v in enumerate(output) if v is None]
    if missing:
        raise EmbeddingAPIError(f"embedding slots unfilled: {missing[:8]}")

    return [vec for vec in output if vec is not None]


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

        # Validate shape — this is a hard requirement now; no zero fallback.
        if embeddings.shape != (n, EMBEDDING_DIM):
            raise EmbeddingAPIError(
                f"Embedding shape mismatch: expected ({n}, {EMBEDDING_DIM}), got {embeddings.shape}"
            )

        # Hard guard: no all-zero rows allowed when an API key was available.
        zero_rows = int(np.sum((embeddings == 0).all(axis=1)))
        if zero_rows > 0:
            raise ValueError(
                f"Embedding build produced {zero_rows}/{n} all-zero rows — poisoned, aborting"
            )

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
