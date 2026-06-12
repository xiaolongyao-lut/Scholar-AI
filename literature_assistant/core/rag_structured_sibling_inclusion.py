"""Same-section structured-sibling inclusion for chat-router retrieval.

Why:
    A15 (pre-rerank chunk-type weighting) gets table/formula candidates
    INTO the rerank pool but cannot force the reranker to keep them in
    final top-K. The reranker tends to prefer narrative passages that
    semantically answer the query, even when the numerical evidence lives
    in a neighbouring table or equation chunk in the same section.

    This module closes that gap deterministically: after the final
    top-K is built, look at every narrative chunk in the result set and
    pull in its structured (table / formula / figure_caption) siblings
    that live on the SAME ``section_path`` (or the same ``page`` as a
    weaker fallback). Siblings are appended after the rerank-decided
    order, never re-rank narrative passages, and respect a small cap
    so a single section with many tables cannot blow up the context
    budget.

    Design choice — section_path over text scanning:
      We do NOT regex-scan content for "Table N" / "Fig. N" / "Eq. N"
      because:
        (a) it's brittle across journals (some papers use bold, some
            use prose like "the equation above", some use bare numbers);
        (b) marker already gives us the structural truth via
            ``section_path`` and ``page``;
        (c) when both narrative AND structured chunks share a section_path,
            the human author already decided they belong together.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

__all__ = [
    "is_sibling_inclusion_enabled",
    "select_structured_siblings",
    "merge_with_siblings",
    "DEFAULT_MAX_SIBLINGS",
    "DEFAULT_STRUCTURED_TYPES",
]


DEFAULT_MAX_SIBLINGS = 2
DEFAULT_STRUCTURED_TYPES = frozenset({"table", "formula", "figure_caption", "equation"})


def is_sibling_inclusion_enabled() -> bool:
    """Resolve the rag_structured_sibling_inclusion flag.

    Off by default. Reads through the feature_flags registry so the UI
    Settings panel and runtime override file both work the same way they
    do for tolf_context / hybrid_retrieval.
    """
    try:
        from feature_flags import is_enabled
        return is_enabled("rag_structured_sibling_inclusion")
    except (ImportError, KeyError):
        # External-cwd / legacy snapshot path: fall back to env var.
        raw = os.getenv("RAG_STRUCTURED_SIBLING_INCLUSION_ENABLED", "")
        return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


def _normalize_section_key(section_path: Any) -> str:
    """Collapse a section_path list into a stable join key.

    section_path is either ``list[str]`` from marker or absent from
    PyMuPDF chunks; treat absent / non-list as the empty key so it never
    matches a real section.
    """
    if isinstance(section_path, list):
        return " > ".join(str(p) for p in section_path if p is not None)
    if isinstance(section_path, str):
        return section_path
    return ""


def _normalize_material_id(value: Any) -> str:
    return str(value or "").strip()


def select_structured_siblings(
    final_results: Sequence[Mapping[str, Any]],
    all_chunks: Sequence[Mapping[str, Any]],
    *,
    max_siblings: int = DEFAULT_MAX_SIBLINGS,
    structured_types: frozenset[str] = DEFAULT_STRUCTURED_TYPES,
) -> list[dict[str, Any]]:
    """Find table / formula / figure_caption chunks that share a section
    with any narrative chunk already in ``final_results``.

    Args:
        final_results: Reranker output, after top-K truncation. Must be
            an iterable of dict-like chunk records carrying at minimum
            ``chunk_id``, ``chunk_type``, and one of
            ``section_path`` / ``page`` / ``material_id``.
        all_chunks: Full corpus the retriever was looking at (the project
            chunk store). Used to find structured neighbours of the
            narrative passages in ``final_results``.
        max_siblings: Hard cap on how many sibling chunks to return,
            across all matching narrative anchors. Prevents a single
            section with many tables from flooding the context.
        structured_types: Set of ``chunk_type`` values that count as
            "structured" siblings.

    Returns:
        A list of shallow-copied chunk dicts that are NOT already in
        ``final_results``, share a (material_id, section_path) with at
        least one narrative chunk in ``final_results``, and whose
        ``chunk_type`` is in ``structured_types``. Bounded by
        ``max_siblings``. Each sibling has a ``sibling_anchor`` field
        added indicating which narrative chunk pulled it in (debug /
        evidence aid).

    Notes:
      - Siblings are NOT scored or sorted by relevance — they ride in on
        the narrative's verified semantic relevance.
      - When section_path is missing on both sides, falls back to
        same-page matching. This is rare on marker chunks but common on
        legacy PyMuPDF projects.
    """
    if max_siblings <= 0:
        return []

    final_ids = {
        str(item.get("chunk_id") or "")
        for item in final_results
        if isinstance(item, Mapping)
    }
    final_ids.discard("")

    # Index narrative chunks in final_results by (material_id, section_key,
    # page) so we can match them efficiently against all_chunks.
    anchors: list[tuple[str, str, Any, str]] = []
    for item in final_results:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("chunk_type") or "") != "narrative":
            continue
        mat = _normalize_material_id(item.get("material_id"))
        sec = _normalize_section_key(item.get("section_path"))
        page = item.get("page")
        anchor_id = str(item.get("chunk_id") or "")
        anchors.append((mat, sec, page, anchor_id))

    if not anchors:
        return []

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in all_chunks:
        if not isinstance(chunk, Mapping):
            continue
        cid = str(chunk.get("chunk_id") or "")
        if not cid or cid in final_ids or cid in seen:
            continue
        ctype = str(chunk.get("chunk_type") or "")
        if ctype not in structured_types:
            continue

        c_mat = _normalize_material_id(chunk.get("material_id"))
        c_sec = _normalize_section_key(chunk.get("section_path"))
        c_page = chunk.get("page")

        for anchor_mat, anchor_sec, anchor_page, anchor_id in anchors:
            if anchor_mat and c_mat and anchor_mat != c_mat:
                continue
            # Prefer section_path match; fall back to same-page when both
            # sides lack a section_path.
            section_match = bool(anchor_sec) and anchor_sec == c_sec
            page_match = (
                not anchor_sec
                and not c_sec
                and anchor_page is not None
                and c_page is not None
                and anchor_page == c_page
            )
            if not (section_match or page_match):
                continue

            sib = dict(chunk)
            sib["sibling_anchor"] = anchor_id
            sib["sibling_reason"] = "section_path" if section_match else "same_page"
            selected.append(sib)
            seen.add(cid)
            if len(selected) >= max_siblings:
                return selected
            break  # one anchor per sibling is enough

    return selected


def merge_with_siblings(
    final_results: Sequence[Mapping[str, Any]],
    siblings: Sequence[Mapping[str, Any]],
    *,
    total_cap: int,
) -> list[dict[str, Any]]:
    """Append siblings after rerank-decided results, capped at ``total_cap``.

    Siblings replace the lowest-ranked narrative entries when capacity is
    tight, but never displace structured chunks already in the result
    set (those are presumed earned via rerank). When ``total_cap`` is
    larger than ``len(final_results) + len(siblings)``, the merged list
    contains everything in original order followed by all siblings.

    Returns:
        A new list of dict shallow copies. Length is at most
        ``total_cap``. Sibling dicts retain the ``sibling_anchor`` /
        ``sibling_reason`` keys added by ``select_structured_siblings``.

    Raises:
        ValueError: If ``total_cap`` is not a positive integer.
    """
    if not isinstance(total_cap, int) or total_cap <= 0:
        raise ValueError("total_cap must be a positive integer")

    base = [dict(item) for item in final_results if isinstance(item, Mapping)]
    sibs = [dict(item) for item in siblings if isinstance(item, Mapping)]
    if not sibs:
        return base[:total_cap]

    if len(base) + len(sibs) <= total_cap:
        return base + sibs

    # Sibling appended at the tail; if base already fills total_cap, drop
    # the lowest-ranked NARRATIVE entry to make room (one drop per sibling
    # to keep the math obvious; never drop existing structured chunks).
    merged = list(base)
    for sib in sibs:
        if len(merged) < total_cap:
            merged.append(sib)
            continue
        # Find lowest-index narrative from the END to drop.
        drop_idx = None
        for idx in range(len(merged) - 1, -1, -1):
            if str(merged[idx].get("chunk_type") or "") == "narrative":
                drop_idx = idx
                break
        if drop_idx is None:
            break  # nothing safe to drop; stop appending siblings.
        merged.pop(drop_idx)
        merged.append(sib)
    return merged[:total_cap]
