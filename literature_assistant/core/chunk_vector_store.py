"""Lightweight in-memory vector store with SiliconFlow embedding API.

Provides dense retrieval for the eval pipeline.
Embeddings are cached to disk to avoid redundant API calls.
Gracefully degrades when no embedding credential is available.
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

import provider_rate_limit
from chunk_size_guard import inspect_text
from llm.gateway import invoke as invoke_model_gateway
from model_call_gateway import CHUNKING_VERSION
from runtime_env import (
    build_embedding_request_payload,
    env_value,
    extract_embedding_vectors,
    is_dashscope_multimodal_embedding_config,
    resolve_embedding_candidates,
    resolve_embedding_config,
    resolve_embedding_request_url,
)
from retrieval_provenance import attach_source_labels
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
DEFAULT_EMBED_BATCH_SIZE = 32
DEFAULT_EMBED_CONCURRENCY = 32  # Safe default, free model supports 10-50 QPS
MAX_EMBED_CONCURRENCY = 50  # Cap at 50 for free models
EMBEDDING_FAILOVER_COOLDOWN_SECONDS = 900.0
DASHSCOPE_MULTIMODAL_MAX_BATCH_SIZE = 20


class EmbeddingAPIError(RuntimeError):
    """Raised when the embedding API cannot produce a usable vector."""


def _normalize_embedding_vector(vector: list[float], *, expected_dim: int = EMBEDDING_DIM) -> list[float]:
    if len(vector) < expected_dim:
        raise EmbeddingAPIError(
            f"embedding vector too short: expected at least {expected_dim} dims, got {len(vector)}"
        )
    if len(vector) == expected_dim:
        return vector
    return vector[:expected_dim]


def _normalize_embedding_vectors(
    vectors: list[list[float]],
    *,
    expected_dim: int = EMBEDDING_DIM,
) -> list[list[float]]:
    return [_normalize_embedding_vector(vector, expected_dim=expected_dim) for vector in vectors]


def _resolve_embed_batch_size(batch_size: int | None) -> int:
    if batch_size is not None:
        return batch_size
    try:
        return max(1, int(os.getenv("EMBEDDING_BATCH_SIZE", str(DEFAULT_EMBED_BATCH_SIZE))))
    except (TypeError, ValueError):
        return DEFAULT_EMBED_BATCH_SIZE


def _effective_embed_batch_size(
    base_url: str,
    model: str,
    batch_size: int | None,
) -> int:
    resolved = _resolve_embed_batch_size(batch_size)
    if is_dashscope_multimodal_embedding_config(base_url, model):
        return min(resolved, DASHSCOPE_MULTIMODAL_MAX_BATCH_SIZE)
    return resolved


def _extract_text(chunk: dict[str, Any]) -> str:
    return str(chunk.get("content") or chunk.get("claim") or chunk.get("text") or "")


def _is_contextualized_chunk(chunk: dict[str, Any]) -> bool:
    content = str(chunk.get("content") or "").lstrip()
    return bool(content.startswith("[") and "]" in content[:300])


def _resolve_effective_cache_path(
    cache_path: Path | None,
    chunks: list[dict[str, Any]],
    model: str = DEFAULT_MODEL,
) -> Path | None:
    if cache_path is None:
        return None
    if any(_is_contextualized_chunk(chunk) for chunk in chunks):
        cache_path = cache_path.with_name(f"{cache_path.stem}_contextual{cache_path.suffix}")
    return _resolve_model_cache_path(cache_path, model, EMBEDDING_DIM)


def _compute_model_hash(model: str, embedding_dim: int = EMBEDDING_DIM) -> str:
    payload = f"{model}|{embedding_dim}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _resolve_model_cache_path(cache_path: Path | None, model: str, embedding_dim: int = EMBEDDING_DIM) -> Path | None:
    if cache_path is None:
        return None
    model_hash = _compute_model_hash(model, embedding_dim)
    return cache_path.with_name(f"{cache_path.stem}_m{model_hash}{cache_path.suffix}")


def _cache_manifest_path(cache_path: Path) -> Path:
    return cache_path.with_suffix(".manifest.json")


def _chunks_hash(chunks: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        payload = json.dumps(chunk, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest.update(payload.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _build_manifest(chunks: list[dict[str, Any]], embeddings: np.ndarray, model: str | None = None) -> dict[str, Any]:
    zero_rows = int(np.sum((embeddings == 0).all(axis=1))) if embeddings.shape[0] > 0 else 0
    return {
        "version": MANIFEST_VERSION,
        "model": model or env_value("SILICONFLOW_EMBEDDING_MODEL", "EMBEDDING_MODEL", default=DEFAULT_MODEL),
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
    expected_model: str | None = None,
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
            f"Embedding cache manifest hash mismatch at {cache_path}: expected {expected_hash}, got {manifest_hash}"
        )

    # ------------------------------------------------------------------
    # 深度增强：模型名称绑定校验
    # ------------------------------------------------------------------
    current_model = expected_model or env_value("SILICONFLOW_EMBEDDING_MODEL", "EMBEDDING_MODEL", default=DEFAULT_MODEL) or DEFAULT_MODEL
    manifest_model = manifest.get("model")
    if manifest_model and manifest_model != current_model:
        raise ValueError(
            f"Embedding cache model mismatch at {cache_path}: "
            f"current {current_model} vs cached {manifest_model}. "
            "Different models produce incompatible vector spaces; please delete cache."
        )

    # ------------------------------------------------------------------
    # 深度增强：随机抽样零向量探测 (Poison Check)
    # ------------------------------------------------------------------
    if expected_count > 0:
        sample_idx = random.randint(0, expected_count - 1)
        if np.all(cached[sample_idx] == 0):
            raise ValueError(f"Poisoned cache detected at {cache_path}: sample index {sample_idx} is all-zeros.")



def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        return vec
    return vec / norm


def _compute_embed_backoff(attempt: int) -> float:
    delay = min(BASE_EMBED_BACKOFF * (2 ** attempt), MAX_EMBED_BACKOFF)
    return delay + random.uniform(0.0, delay)


def _embedding_endpoint(base_url: str, model: str | None = None) -> str:
    return resolve_embedding_request_url(base_url, model)


def _embedding_request_token_count(texts: list[str]) -> int:
    return sum(max(1, count_tokens(text)) for text in texts)


def _model_accepts_dimensions(model: str | None) -> bool:
    """Return True only for embedding models that document a ``dimensions`` param.

    Why:
        SiliconFlow's ``BAAI/bge-m3`` returns HTTP 400 ``code=20015 parameter is
        invalid`` when ``dimensions`` is present in the payload, because bge-m3
        is natively 1024-dim and does not expose runtime truncation. In
        contrast, ``Qwen/Qwen3-Embedding-8B`` is natively 4096-dim and requires
        ``dimensions=1024`` to match the rest of the pipeline.

        Hard-coding ``dimensions=EMBEDDING_DIM`` for all models therefore
        breaks bge-m3 backfill / build paths. We allow-list only the models
        known to accept the parameter.
    """
    if not model:
        return False
    lowered = model.strip().lower()
    # Qwen3 embedding family advertises configurable dimensions (1024/512/...).
    if "qwen3-embedding" in lowered:
        return True
    # OpenAI text-embedding-3-* family also supports dimensions.
    if "text-embedding-3" in lowered:
        return True
    return False


def _embed_dimensions_arg(model: str | None) -> int | None:
    """Return ``EMBEDDING_DIM`` when the model accepts it, else ``None``."""
    return EMBEDDING_DIM if _model_accepts_dimensions(model) else None


def _invoke_embedding_http(text: str, api_key: str, base_url: str, model: str) -> list[float]:
    # Security gate: validate endpoint before sending credentials
    try:
        from provider_endpoint_policy import (
            TrustSource,
            validate_endpoint,
        )

        decision = validate_endpoint(
            base_url,
            trust_source=TrustSource.RUNTIME_USER_CONFIRMED,
            allow_loopback_http=True,
        )
        if not decision.allowed:
            raise EmbeddingAPIError(
                f"Embedding endpoint rejected by security policy: {base_url} "
                f"(reason: {decision.reason})"
            )
    except EmbeddingAPIError:
        raise
    except Exception as policy_exc:
        raise EmbeddingAPIError(
            f"Endpoint policy check failed for {base_url}: {policy_exc}"
        ) from policy_exc

    payload = build_embedding_request_payload(
        [text],
        base_url=base_url,
        model=model,
        dimensions=_embed_dimensions_arg(model),
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    provider_rate_limit.maybe_wait_for_rate_limit_sync(
        base_url,
        kind="embedding",
        token_count=_embedding_request_token_count([text]),
    )
    with httpx.Client(timeout=60.0) as sync_client:
        resp = sync_client.post(
            _embedding_endpoint(base_url, model),
            headers=headers,
            json=payload,
        )
    if resp.status_code != 200:
        body = (resp.text or "")[:240]
        raise EmbeddingAPIError(
            f"embedding API failed (status={resp.status_code}, body={body!r})"
        )
    vectors = extract_embedding_vectors(resp.json())
    if len(vectors) != 1:
        raise EmbeddingAPIError("embedding API returned invalid single-text payload")
    return _normalize_embedding_vector(vectors[0])


_DEFAULT_INVOKE_EMBEDDING_HTTP = _invoke_embedding_http


def _make_embedding_failover_pool(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    default_base_url: str = DEFAULT_BASE_URL,
    default_model: str = DEFAULT_MODEL,
):
    try:
        from key_pool import Credential, KeyPool
    except Exception:
        return None

    candidates = resolve_embedding_candidates(
        api_key,
        base_url=base_url,
        model=model,
        default_base_url=default_base_url,
        default_model=default_model,
    )
    if not candidates:
        return None

    creds = [
        Credential(
            category="embedding",
            provider=source,
            api_key=candidate_key,
            base_url=candidate_base_url,
            model=candidate_model,
        )
        for candidate_key, candidate_base_url, candidate_model, source in candidates
    ]
    return KeyPool(
        {"embedding": creds, "rerank": [], "generation": []},
        cooldown_seconds=EMBEDDING_FAILOVER_COOLDOWN_SECONDS,
    )


async def _post_embed_batch(
    client: httpx.AsyncClient,
    batch: list[str],
    api_key: str,
    base_url: str,
    model: str,
) -> list[list[float]]:
    if _invoke_embedding_http is not _DEFAULT_INVOKE_EMBEDDING_HTTP:
        return [_invoke_embedding_http(text, api_key, base_url, model) for text in batch]

    # Security gate: validate endpoint before sending credentials
    try:
        from provider_endpoint_policy import (
            TrustSource,
            validate_endpoint,
        )

        decision = validate_endpoint(
            base_url,
            trust_source=TrustSource.RUNTIME_USER_CONFIRMED,
            allow_loopback_http=True,
        )
        if not decision.allowed:
            raise EmbeddingAPIError(
                f"Batch embedding endpoint rejected by security policy: {base_url} "
                f"(reason: {decision.reason})"
            )
    except EmbeddingAPIError:
        raise
    except Exception as policy_exc:
        raise EmbeddingAPIError(
            f"Endpoint policy check failed for {base_url}: {policy_exc}"
        ) from policy_exc

    """POST one batch of texts to /embeddings with retry. Raises on failure."""
    payload = build_embedding_request_payload(
        batch,
        base_url=base_url,
        model=model,
        dimensions=_embed_dimensions_arg(model),
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    token_count = _embedding_request_token_count(batch)
    last_status: int | None = None
    last_body: str = ""
    for attempt in range(MAX_EMBED_RETRIES):
        try:
            await provider_rate_limit.maybe_wait_for_rate_limit_async(
                base_url,
                kind="embedding",
                token_count=token_count,
            )
            resp = await client.post(
                _embedding_endpoint(base_url, model),
                headers=headers,
                json=payload,
            )
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.TimeoutException) as exc:
            if attempt < MAX_EMBED_RETRIES - 1:
                await asyncio.sleep(_compute_embed_backoff(attempt))
                continue
            raise EmbeddingAPIError(f"embedding transport error: {exc}") from exc

        if resp.status_code == 200:
            return _normalize_embedding_vectors(extract_embedding_vectors(resp.json()))

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


async def _batch_embed_api_only(
    texts: list[str],
    api_key: str,
    base_url: str,
    model: str,
    batch_size: int | None = None,
    concurrency: int | None = None,
    stage: str | None = None,
    credential_pool: Any | None = None,
) -> list[list[float]]:
    """Embed texts with token-aware split+mean-pool for oversized entries.

    Supports parallel batch embedding via semaphore (configurable via EMBED_CONCURRENCY env var).
    Raises `EmbeddingAPIError` on transport/HTTP failures — no silent zero fallback.

    NOTE: This is the API-only embed path. Public callers should use
    ``_batch_embed`` which wraps this with an offline local-model fallback
    (``local_embedding_adapter``) so a transient API outage does not break
    backfill / query when weights are cached on disk.
    """
    if not texts:
        return []

    if credential_pool is not None:
        async def _invoke_with_credential(cred: Any) -> list[list[float]]:
            return await _batch_embed_api_only(
                texts,
                cred.api_key,
                cred.base_url,
                cred.model,
                batch_size=batch_size,
                concurrency=concurrency,
                stage=stage,
                credential_pool=None,
            )

        return await credential_pool.try_call_async(
            "embedding",
            _invoke_with_credential,
            cooldown_on=lambda _exc: True,
        )

    batch_size = _effective_embed_batch_size(base_url, model, batch_size)
    concurrency = int(os.getenv("EMBED_CONCURRENCY", str(concurrency or DEFAULT_EMBED_CONCURRENCY)))
    semaphore = asyncio.Semaphore(concurrency)

    # Normalize empty → "empty" placeholder (preserves historical behavior).
    normalized = [t if (t and t.strip()) else "empty" for t in texts]

    # Create HTTP client that will be shared by all async operations
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Tag long ones for split+mean-pool (legacy compatibility for moderately long chunks).
        lengths = [count_tokens(t) for t in normalized]
        long_slots = {i for i, n in enumerate(lengths) if n > SAFE_EMBED_TOKENS}

        if long_slots:
            logger.info(
                "embed: %d/%d texts exceed SAFE_EMBED_TOKENS=%d; routing through split+mean-pool",
                len(long_slots),
                len(normalized),
                SAFE_EMBED_TOKENS,
            )

        if len(normalized) == 1 and 0 not in long_slots:
            def _invoke_single() -> list[float]:
                return _invoke_embedding_http(normalized[0], api_key, base_url, model)

            vector = await asyncio.to_thread(
                invoke_model_gateway,
                kind="embedding",
                cache_key_parts={
                    "model": model,
                    "normalized_text": normalized[0],
                    "chunking_version": CHUNKING_VERSION,
                },
                payload={
                    "model": model,
                    "input": [normalized[0]],
                    "encoding_format": "float",
                    "dimensions": EMBEDDING_DIM,
                },
                invoke_fn=_invoke_single,
                validate_result=lambda value: isinstance(value, list) and len(value) >= EMBEDDING_DIM,
                stage=stage,
            )
            return [_normalize_embedding_vector(vector)]

        output: list[list[float] | None] = [None] * len(normalized)

        # 1) Fill long slots via split+mean-pool (one text at a time, serial)
        for i in sorted(long_slots):
            output[i] = await _embed_single_long(normalized[i], api_key, base_url, model, client)

        # 2) Batch-embed the rest (parallel via semaphore)
        regular_indices = [i for i in range(len(normalized)) if i not in long_slots]

        async def _process_batch(batch_texts: list[str]) -> list[list[float]]:
            async with semaphore:
                return await _post_embed_batch(client, batch_texts, api_key, base_url, model)

        async def embed_window(start: int, end: int) -> None:
            window = regular_indices[start:end]
            batch_texts = [normalized[i] for i in window]
            sub_raw = await _process_batch(batch_texts)
            if len(sub_raw) != len(window):
                raise EmbeddingAPIError(
                    f"embedding API returned {len(sub_raw)} vectors for {len(window)} inputs"
                )
            for slot_idx, vec in zip(window, sub_raw):
                output[slot_idx] = vec

        # Split windows across workers
        for i in range(0, len(regular_indices), batch_size):
            await embed_window(i, min(i + batch_size, len(regular_indices)))

    # Final sanity: every slot filled.
    missing = [i for i, v in enumerate(output) if v is None]
    if missing:
        raise EmbeddingAPIError(f"embedding slots unfilled: {missing[:8]}")

    return _normalize_embedding_vectors([vec for vec in output if vec is not None])

    # Split windows across workers
    for i in range(0, len(regular_indices), batch_size):
        await embed_window(i, min(i + batch_size, len(regular_indices)))

    # Final sanity: every slot filled.
    missing = [i for i, v in enumerate(output) if v is None]
    if missing:
        raise EmbeddingAPIError(f"embedding slots unfilled: {missing[:8]}")

    return [vec for vec in output if vec is not None]


async def _batch_embed(
    texts: list[str],
    api_key: str,
    base_url: str,
    model: str,
    batch_size: int | None = None,
    concurrency: int | None = None,
    stage: str | None = None,
    credential_pool: Any | None = None,
) -> list[list[float]]:
    """Public embed entry — API-first with local sentence-encoder fallback.

    Behavior:
      1. Try ``_batch_embed_api_only`` (the upstream HTTP path).
      2. On ``EmbeddingAPIError`` (transport/HTTP failure or unfilled slots),
         check ``local_embedding_adapter.is_available()`` — if true, encode
         via the locally-cached SentenceTransformer (default ``BAAI/bge-m3``)
         and return those vectors. Same dim, same normalize convention, so
         downstream cosine math doesn't care which path produced the vectors.
      3. If local is unavailable too, re-raise the original API error — no
         silent degradation, callers see the real upstream error.

    Why this layering: the API is the cheap fast path in normal operation
    (no model load, no GPU memory). Local fallback only kicks in when the
    user actually needs it (offline / DNS-blocked / 403 / rate-limit).
    Mirrors the local_rerank_adapter design from f9a319b1.
    """
    if not texts:
        return []
    try:
        return await _batch_embed_api_only(
            texts,
            api_key,
            base_url,
            model,
            batch_size=batch_size,
            concurrency=concurrency,
            stage=stage,
            credential_pool=credential_pool,
        )
    except EmbeddingAPIError as api_exc:
        try:
            from local_embedding_adapter import aencode_texts, is_available
        except ImportError as import_exc:
            logger.warning(
                "embed: local fallback adapter not importable (%s); re-raising API error",
                import_exc,
            )
            raise api_exc
        if not is_available():
            logger.info(
                "embed: API failed (%s) and local fallback unavailable; re-raising",
                api_exc,
            )
            raise api_exc
        logger.warning(
            "embed: API failed (%s); attempting local sentence-encoder fallback",
            api_exc,
        )
        normalized = [t if (t and t.strip()) else "empty" for t in texts]
        local_vectors = await aencode_texts(normalized, target_dim=EMBEDDING_DIM)
        if local_vectors is None:
            logger.warning("embed: local fallback returned None; re-raising API error")
            raise api_exc
        if len(local_vectors) != len(texts):
            logger.warning(
                "embed: local fallback returned %d vectors for %d inputs; re-raising API error",
                len(local_vectors),
                len(texts),
            )
            raise api_exc
        return _normalize_embedding_vectors(local_vectors)


async def batch_embed_texts(
    texts: list[str],
    *,
    api_key: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    batch_size: int | None = None,
    concurrency: int | None = None,
    stage: str | None = None,
) -> list[list[float]]:
    """Public helper for provider-aware text embedding outside ChunkVectorStore.

    Reuses the same embedding resolution, batching, token guards, and
    credential failover path as the vector-store build/query flows.
    """
    resolved_key, resolved_base, resolved_model = resolve_embedding_config(
        api_key,
        base_url=base_url,
        model=model,
        default_base_url=base_url,
        default_model=model,
        probe_candidates=False,
    )
    if not resolved_key:
        raise EmbeddingAPIError("No embedding credential available")

    embedding_pool = _make_embedding_failover_pool(
        api_key=api_key,
        base_url=base_url,
        model=model,
        default_base_url=base_url,
        default_model=model,
    )

    return await _batch_embed(
        texts,
        resolved_key,
        resolved_base,
        resolved_model,
        batch_size=batch_size,
        concurrency=concurrency,
        stage=stage,
        credential_pool=embedding_pool,
    )


class ChunkVectorStore:
    """In-memory vector index for chunk-level dense retrieval."""

    def __init__(
        self,
        chunks: list[dict[str, Any]],
        embeddings: np.ndarray,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        embedding_pool: Any | None = None,
    ):
        self.chunks = chunks
        self._embeddings = embeddings  # (n_chunks, dim)
        self._api_key, self._base_url, self._model = resolve_embedding_config(
            api_key,
            base_url=base_url,
            model=model,
            default_base_url=DEFAULT_BASE_URL,
            default_model=DEFAULT_MODEL,
            probe_candidates=False,
        )
        if not self._model:
            self._model = DEFAULT_MODEL
        self._embedding_pool = embedding_pool or _make_embedding_failover_pool(
            api_key=self._api_key,
            base_url=self._base_url,
            model=self._model,
            default_base_url=self._base_url or DEFAULT_BASE_URL,
            default_model=self._model or DEFAULT_MODEL,
        )

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
        batch_size: int | None = None,
        concurrency: int | None = None,
        strict_cache_guard: bool = True,
    ) -> ChunkVectorStore:
        """Build index. Uses cached embeddings when available, else calls API."""
        if not chunks:
            return cls([], np.zeros((0, EMBEDDING_DIM), dtype=np.float32))

        n = len(chunks)
        for i, chunk in enumerate(chunks):
            text_metrics = inspect_text(_extract_text(chunk))
            if text_metrics["is_oversize"]:
                raise EmbeddingAPIError(
                    f"chunk hard limit exceeded before embedding at index {i}: "
                    f"{text_metrics['char_count']} chars (max {text_metrics['max_chars']}) or "
                    f"{text_metrics['token_count']} tokens (max {text_metrics['max_tokens']})"
                )

        resolved_key, resolved_base, resolved_model = resolve_embedding_config(
            api_key,
            base_url=base_url,
            model=model,
            default_base_url=base_url,
            default_model=model,
            probe_candidates=False,
        )
        embedding_pool = _make_embedding_failover_pool(
            api_key=api_key,
            base_url=base_url,
            model=model,
            default_base_url=base_url,
            default_model=model,
        )
        if not resolved_model or "bge-m3" in resolved_model.lower():
            resolved_model = "BAAI/bge-m3"
        effective_cache_path = _resolve_effective_cache_path(cache_path, chunks, model=resolved_model)

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
                    expected_model=resolved_model,
                )
                logger.info("Loaded %d cached embeddings from %s (manifest-verified)", n, effective_cache_path)
                return cls(
                    chunks,
                    cached.astype(np.float32),
                    api_key=resolved_key,
                    base_url=resolved_base,
                    model=resolved_model,
                    embedding_pool=embedding_pool,
                )

            try:
                cached = np.load(str(effective_cache_path))
                if cached.shape[0] == n and cached.shape[1] == EMBEDDING_DIM:
                    logger.info("Loaded %d cached embeddings from %s", n, effective_cache_path)
                    return cls(
                        chunks,
                        cached.astype(np.float32),
                        api_key=resolved_key,
                        base_url=resolved_base,
                        model=resolved_model,
                        embedding_pool=embedding_pool,
                    )
            except Exception:
                pass

        # 2. Try using pre-computed embeddings from chunk dicts
        pre = [chunk.get("embedding") for chunk in chunks]
        if all(e is not None and len(e) >= EMBEDDING_DIM for e in pre):
            embeddings = np.array(pre, dtype=np.float32)[:, :EMBEDDING_DIM]
            _save_cache(effective_cache_path, embeddings, chunks, model=resolved_model)
            logger.info("Using %d pre-computed embeddings from chunks", n)
            return cls(
                chunks,
                embeddings,
                api_key=resolved_key,
                base_url=resolved_base,
                model=resolved_model,
                embedding_pool=embedding_pool,
            )

        # 3. Compute via API
        if not resolved_key:
            logger.warning(
                "No embedding credential available; dense retrieval disabled for %d chunks",
                n,
            )
            return cls(
                chunks,
                np.zeros((n, EMBEDDING_DIM), dtype=np.float32),
                embedding_pool=embedding_pool,
            )

        texts = [_extract_text(c) for c in chunks]
        logger.info("Embedding %d chunks via API (%s)...", n, resolved_model)
        raw = await _batch_embed(
            texts,
            resolved_key,
            resolved_base,
            resolved_model,
            batch_size=batch_size,
            stage="build",
            credential_pool=embedding_pool,
        )
        embeddings = np.array(_normalize_embedding_vectors(raw), dtype=np.float32)

        # Validate shape — this is a hard requirement now; no zero fallback.
        if embeddings.shape != (n, EMBEDDING_DIM):
            raise EmbeddingAPIError(
                f"Embedding shape mismatch: expected ({n}, {EMBEDDING_DIM}), got {embeddings.shape}"
            )

        # Hard guard: no all-zero rows allowed when an embedding credential was available.
        zero_rows = int(np.sum((embeddings == 0).all(axis=1)))
        if zero_rows > 0:
            raise ValueError(
                f"Embedding build produced {zero_rows}/{n} all-zero rows — poisoned, aborting"
            )

        _save_cache(effective_cache_path, embeddings, chunks, model=resolved_model)

        return cls(
            chunks,
            embeddings,
            api_key=resolved_key,
            base_url=resolved_base,
            model=resolved_model,
            embedding_pool=embedding_pool,
        )

    async def embed_query(self, query_text: str) -> np.ndarray | None:
        """Embed a single query. Returns None if no embedding credential."""
        if not self._api_key or not self.has_embeddings:
            return None
        results = await _batch_embed(
            [query_text],
            self._api_key,
            self._base_url,
            self._model,
            batch_size=1,
            stage="query",
            credential_pool=self._embedding_pool,
        )
        if results and len(results[0]) >= EMBEDDING_DIM:
            return np.array(results[0][:EMBEDDING_DIM], dtype=np.float32)
        return None

    async def batch_embed_queries(
        self, texts: list[str], batch_size: int | None = None
    ) -> list[np.ndarray | None]:
        """Embed multiple queries in batch. Returns list parallel to *texts*."""
        if not self._api_key or not self.has_embeddings or not texts:
            return [None] * len(texts)
        raw = await _batch_embed(
            texts,
            self._api_key,
            self._base_url,
            self._model,
            batch_size=batch_size,
            stage="query",
            credential_pool=self._embedding_pool,
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
            item = attach_source_labels(dict(self.chunks[int(idx)]), ["dense"], source_hint="dense")
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


def _save_cache(
    cache_path: Path | None,
    embeddings: np.ndarray,
    chunks: list[dict[str, Any]],
    model: str | None = None,
) -> None:
    if cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            np.save(str(cache_path), embeddings)
            manifest = _build_manifest(chunks, embeddings, model=model)
            _cache_manifest_path(cache_path).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("Saved embedding cache to %s", cache_path)
        except Exception as e:
            logger.warning("Failed to save embedding cache: %s", e)
