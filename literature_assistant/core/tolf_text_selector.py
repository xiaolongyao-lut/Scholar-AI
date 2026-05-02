"""Default-off text-only TOLF context selector for local project chunks."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Mapping, Sequence

import numpy as np

from layers.tolf_engine import TOLFConfig, TOLFEngine
from retrieval_provenance import merge_source_labels


_TOKEN_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+", re.UNICODE)
_NUMERIC_EVIDENCE_RE = re.compile(
    r"\b\d+(?:\.\d+)?(?:\s*(?:%|wt\.%|um|μm|mm|nm|mpa|gpa|hv|°c|k|w|kw))\b",
    re.IGNORECASE,
)


def _tokenize_text(value: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(value)]


def _token_bucket(token: str, dim: int) -> int:
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % dim


def make_local_text_embeddings(texts: Sequence[str], *, dim: int = 64) -> np.ndarray:
    """Create deterministic local embeddings for zero-cost TOLF context trials.

    Args:
        texts: Text sequence to vectorize. Each item is coerced to ``str``.
        dim: Positive embedding dimension.

    Returns:
        ``float32`` matrix with shape ``(len(texts), dim)``.

    Raises:
        ValueError: If ``dim`` is not positive.
    """
    if not isinstance(dim, int) or dim <= 0:
        raise ValueError("dim must be a positive integer")

    matrix = np.zeros((len(texts), dim), dtype=np.float32)
    for row_index, text in enumerate(texts):
        for token in _tokenize_text(str(text or "")):
            matrix[row_index, _token_bucket(token, dim)] += 1.0

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    nonzero = norms[:, 0] > 0.0
    matrix[nonzero] = matrix[nonzero] / norms[nonzero]
    return matrix


def _chunk_content(chunk: Mapping[str, Any]) -> str:
    return str(
        chunk.get("content")
        or chunk.get("raw_content")
        or chunk.get("text")
        or chunk.get("source_text")
        or ""
    ).strip()


def _chunk_id(chunk: Mapping[str, Any], index: int) -> str:
    return str(chunk.get("chunk_id") or chunk.get("id") or f"chunk_{index}").strip()


def _infer_point_type(content: str, raw_point_type: Any) -> str:
    existing = str(raw_point_type or "").strip().lower()
    if existing:
        return existing

    lowered = content.lower()
    if _NUMERIC_EVIDENCE_RE.search(lowered) or any(
        token in lowered for token in ("increased", "decreased", "improved", "result", "结果")
    ):
        return "result"
    if any(token in lowered for token in ("method", "parameter", "process", "experiment", "工艺", "参数", "实验")):
        return "method"
    if any(token in lowered for token in ("mechanism", "cause", "because", "机理", "原因")):
        return "mechanism"
    if any(token in lowered for token in ("review", "background", "previous", "综述", "背景")):
        return "background"
    return "discussion"


def _normalize_chunk(chunk: Mapping[str, Any], index: int) -> dict[str, Any] | None:
    content = _chunk_content(chunk)
    if not content:
        return None

    chunk_id = _chunk_id(chunk, index)
    if not chunk_id:
        return None

    normalized = dict(chunk)
    normalized["id"] = chunk_id
    normalized["chunk_id"] = chunk_id
    normalized["content"] = content
    normalized["point_type"] = _infer_point_type(content, chunk.get("point_type"))
    normalized["_tolf_original_index"] = index
    return normalized


def _cosine_prefilter(
    query: str,
    chunks: list[dict[str, Any]],
    *,
    max_candidates: int,
    embedding_dim: int,
) -> list[dict[str, Any]]:
    if len(chunks) <= max_candidates:
        return chunks

    texts = [query, *[str(chunk["content"]) for chunk in chunks]]
    embeddings = make_local_text_embeddings(texts, dim=embedding_dim)
    query_vec = embeddings[0]
    chunk_matrix = embeddings[1:]
    scores = chunk_matrix @ query_vec
    ranked_indices = np.argsort(-scores, kind="stable")[:max_candidates]
    return [chunks[int(index)] for index in ranked_indices]


def _query_overlap_tokens(query: str, content: str) -> list[str]:
    query_tokens = set(_tokenize_text(query))
    content_tokens = set(_tokenize_text(content))
    return sorted(query_tokens & content_tokens)


def select_tolf_context_chunks(
    query: str,
    chunks: Sequence[Mapping[str, Any]],
    *,
    top_k: int,
    embedding_dim: int = 64,
    max_candidates: int = 45,
) -> list[dict[str, Any]]:
    """Select project chunks through a zero-cost text-only TOLF evidence gate.

    Args:
        query: Non-empty user query.
        chunks: Candidate project chunk dictionaries with provenance fields.
        top_k: Positive number of chunks to return.
        embedding_dim: Positive local hashing embedding dimension.
        max_candidates: Positive cap applied before TOLF to avoid optional UMAP.

    Returns:
        Selected chunk dictionaries with TOLF scores and provenance labels.

    Raises:
        ValueError: If query, top_k, embedding_dim, or max_candidates are invalid.
        TypeError: If chunks is not a non-string sequence.
    """
    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise ValueError("query must be a non-empty string")
    if isinstance(chunks, (str, bytes)) or not isinstance(chunks, Sequence):
        raise TypeError("chunks must be a sequence of mapping objects")
    if not isinstance(top_k, int) or top_k <= 0:
        raise ValueError("top_k must be a positive integer")
    if not isinstance(embedding_dim, int) or embedding_dim <= 0:
        raise ValueError("embedding_dim must be a positive integer")
    if not isinstance(max_candidates, int) or max_candidates <= 0:
        raise ValueError("max_candidates must be a positive integer")

    normalized_chunks: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        if isinstance(chunk, Mapping):
            normalized = _normalize_chunk(chunk, index)
            if normalized is not None:
                normalized_chunks.append(normalized)

    if not normalized_chunks:
        return []

    candidate_cap = max(top_k, min(max_candidates, max(top_k, embedding_dim + 1)))
    candidates = _cosine_prefilter(
        normalized_query,
        normalized_chunks,
        max_candidates=candidate_cap,
        embedding_dim=embedding_dim,
    )
    if not candidates:
        return []

    aspect_queries = TOLFEngine().generate_aspect_queries(normalized_query)
    embedding_texts = [str(chunk["content"]) for chunk in candidates]
    aspect_texts = list(aspect_queries.values())
    chunk_embeddings = make_local_text_embeddings(embedding_texts, dim=embedding_dim)
    aspect_embeddings = make_local_text_embeddings(aspect_texts, dim=embedding_dim)

    config = TOLFConfig(
        activation_threshold=0.1,
        evidence_threshold=0.2,
        umap_n_components=max(embedding_dim, len(candidates)),
        umap_n_neighbors=2,
        log_small_corpus_fallback=False,
    )
    fish_results = TOLFEngine(config).run(
        goal=normalized_query,
        chunks=[dict(chunk) for chunk in candidates],
        embeddings=chunk_embeddings,
        aspect_query_embeddings=aspect_embeddings,
    )

    by_chunk_id = {str(chunk["chunk_id"]): chunk for chunk in candidates}
    selected: list[dict[str, Any]] = []
    for rank, fish in enumerate(fish_results[:top_k], start=1):
        source = by_chunk_id.get(str(fish.chunk_id))
        if source is None:
            continue
        updated = dict(source)
        updated["score"] = round(float(fish.activation_score), 4)
        updated["tolf_activation_score"] = round(float(fish.activation_score), 4)
        updated["tolf_evidence_score"] = round(float(fish.evidence_score), 4)
        updated["tolf_point_type"] = fish.point_type
        updated["tolf_rank"] = rank
        updated["query_overlap_tokens"] = _query_overlap_tokens(
            normalized_query,
            str(updated.get("content") or ""),
        )
        updated["source_labels"] = merge_source_labels(
            updated.get("source_labels"),
            "tolf_text_selector",
        )
        updated["source_hint"] = "+".join(updated["source_labels"])
        selected.append(updated)

    return selected
