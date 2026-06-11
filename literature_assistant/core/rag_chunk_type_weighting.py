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

When the flag is ON the weights table is a baseline (all 1.0) — tuning
权重值 needs real RAG goldset evaluation (deferred per OPEN_THREADS A15).

This file does NOT modify any retriever code path. Retriever integration
is intentionally left as a future slice so RAG behavior stays unchanged
until a callsite consciously imports + invokes this hook.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


__all__ = [
    "CHUNK_TYPE_WEIGHTS",
    "apply_chunk_type_weights",
    "is_weighting_enabled",
]


# Baseline weights — all 1.0 means "flag-on has no scoring effect yet"
# (intentional: real tuning requires a RAG goldset evaluation, see plan §6
# and OPEN_THREADS A15). Future tuning replaces these values; the flag
# semantics — apply table to score — stays the same.
CHUNK_TYPE_WEIGHTS: dict[str, float] = {
    "narrative": 1.0,
    "heading": 1.0,
    "table": 1.0,
    "formula": 1.0,
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
