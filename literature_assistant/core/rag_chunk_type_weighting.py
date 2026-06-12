# -*- coding: utf-8 -*-
"""RAG chunk-type weighting hook — A15 feature flag framework.

Plan: docs/plans/active/2026-06-11-marker-pdf-rag-pipeline-plan.md §6

Purpose:
  Provide a pure-function hook ``apply_chunk_type_weights(scored_chunks)``
  that retriever / rerank fusion can call to multiply each candidate's
  score by a per-``chunk_type`` weight. When the
  ``rag_chunk_type_weighting`` feature flag is OFF (default), the hook is
  a no-op: returns ``list(candidates)`` as-is, NO score mutation, NO
  re-sort. Critical 稳定优先 contract: byte-level zero impact when off.

When the flag is ON the weights table is tuned for the pre-rerank candidate
pool: table/formula chunks are easier to forward to the expensive cross
encoder, while final rerank scores still decide the answer order.

The production retriever calls ``prioritize_candidates_for_rerank`` before
the reranker candidate cap is applied. Final answer ordering still belongs
to the reranker score, not to these chunk-type weights.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


__all__ = [
    "CHUNK_TYPE_WEIGHTS",
    "apply_chunk_type_weights",
    "prioritize_candidates_for_rerank",
    "is_weighting_enabled",
]


# Conservative pre-rerank candidate weights. They are intentionally applied
# before reranking so table/formula evidence can enter the cross-encoder pool
# without overriding final cross-encoder relevance scores.
CHUNK_TYPE_WEIGHTS: dict[str, float] = {
    "narrative": 1.0,
    "heading": 0.5,
    "table": 3.0,
    "formula": 2.0,
    "figure_caption": 1.0,
    "list": 1.0,
    "code": 1.0,
    "image_caption": 1.0,
}


def is_weighting_enabled() -> bool:
    """Cheap probe — defensive against import-cycle issues in early boot."""
    try:
        from feature_flags import is_enabled
        return is_enabled("rag_chunk_type_weighting")
    except (ImportError, KeyError):
        return False


def apply_chunk_type_weights(
    candidates: Iterable[Mapping[str, Any]] | list[dict[str, Any]],
    *,
    score_key: str = "score",
    chunk_type_key: str = "chunk_type",
    weights: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Apply per-chunk_type score weights.

    Args:
        candidates: Iterable of dict-like chunk records (must have a
            ``score`` and ``chunk_type`` field at the given keys).
        score_key: Name of the score field (default ``"score"``).
        chunk_type_key: Name of the chunk_type field (default ``"chunk_type"``).
        weights: Optional override of ``CHUNK_TYPE_WEIGHTS`` (for testing
            and future per-call tuning).

    Returns:
        - When ``rag_chunk_type_weighting`` flag is OFF: returns
          ``list(candidates)`` as-is. NO score mutation, NO re-sort.
        - When flag is ON: returns a new list of dict shallow copies with
          ``score_key`` multiplied by the weight for the candidate's
          ``chunk_type``, then sorted by the adjusted score descending.
          Original candidate dicts are NOT mutated.
    """
    if not is_weighting_enabled():
        return list(candidates)

    table = weights if weights is not None else CHUNK_TYPE_WEIGHTS
    out: list[dict[str, Any]] = []
    for c in candidates:
        if not isinstance(c, Mapping):
            out.append(dict(c) if hasattr(c, "__iter__") else {"value": c})
            continue
        adjusted = dict(c)
        ctype = c.get(chunk_type_key)
        weight = table.get(str(ctype) if ctype is not None else "", 1.0)
        try:
            raw_score = float(c.get(score_key) or 0.0)
        except (TypeError, ValueError):
            raw_score = 0.0
        adjusted[score_key] = raw_score * weight
        out.append(adjusted)
    out.sort(key=lambda c: float(c.get(score_key) or 0.0), reverse=True)
    return out


def prioritize_candidates_for_rerank(
    candidates: Iterable[Mapping[str, Any]] | list[dict[str, Any]],
    *,
    score_key: str = "hybrid_score",
    chunk_type_key: str = "chunk_type",
    candidate_limit: int,
    weights: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Return the pre-rerank candidate pool with optional type-aware priority.

    Args:
        candidates: Ranked chunk records from the hybrid retriever.
        score_key: Base retrieval score field used for candidate priority.
        chunk_type_key: Chunk type metadata field.
        candidate_limit: Positive maximum number of candidates forwarded to
            the expensive reranker.
        weights: Optional per-type weights for tests and later tuning.

    Returns:
        When the feature flag is disabled, the first ``candidate_limit`` rows
        are returned unchanged as dictionaries. When enabled, shallow copies are
        sorted by ``score_key * weight(chunk_type)`` before truncation, while the
        original score field is preserved for downstream filtering and logging.

    Raises:
        ValueError: If ``candidate_limit`` is not positive.
    """

    if not isinstance(candidate_limit, int) or candidate_limit <= 0:
        raise ValueError("candidate_limit must be a positive integer")

    rows = [dict(item) for item in candidates if isinstance(item, Mapping)]
    if not rows:
        return []

    if not is_weighting_enabled():
        return rows[:candidate_limit]

    table = weights if weights is not None else CHUNK_TYPE_WEIGHTS

    def priority(item: Mapping[str, Any]) -> float:
        ctype = item.get(chunk_type_key)
        weight = table.get(str(ctype) if ctype is not None else "", 1.0)
        try:
            base_score = float(item.get(score_key) or 0.0)
        except (TypeError, ValueError):
            base_score = 0.0
        return base_score * weight

    ranked = sorted(enumerate(rows), key=lambda pair: (priority(pair[1]), -pair[0]), reverse=True)
    return [item for _, item in ranked[:candidate_limit]]
