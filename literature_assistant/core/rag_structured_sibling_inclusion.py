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
import re
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

# Regex for "Table 2" / "Fig. 4" / "Figure 4" / "Eq. (1)" / "Equation 3"
# style references inside narrative content. Used to rank candidate
# siblings by literal mention.
_NARRATIVE_REF_RE = re.compile(
    r"\b(Table|Fig\.?|Figure|Eq\.?|Equation)\s*[\.\(\[]?\s*(\d+)",
    re.IGNORECASE,
)

# Identifier inside a sibling chunk's content body:
#   - "Table 1 EDS data..." / "Table 2 Creep data..."
#   - "Fig. 4 ..." / "Figure 4 ..."
#   - "\tag{1}" / "\tag{2}" inside LaTeX formulas
_SIBLING_ID_HEAD_RE = re.compile(
    r"\b(Table|Fig\.?|Figure|Eq\.?|Equation)\s*(\d+)",
    re.IGNORECASE,
)
_SIBLING_ID_TAG_RE = re.compile(r"\\tag\{?\s*(\d+)\s*\}?")


_REF_FAMILY = {
    "table": "table",
    "fig": "figure",
    "fig.": "figure",
    "figure": "figure",
    "eq": "equation",
    "eq.": "equation",
    "equation": "equation",
}


def _normalize_family(raw: str) -> str:
    return _REF_FAMILY.get(str(raw).lower().rstrip("."), str(raw).lower())


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


def _extract_narrative_refs(content: str) -> list[tuple[str, str]]:
    """Return ordered (family, number) tuples mentioned in narrative content.

    Order matters: earlier mentions outrank later ones, so when the
    anchor narrative says "Table 2 ... Fig. 4 ..." we prefer the Table 2
    sibling over Fig 4 if max_siblings forces a choice.

    Family names are normalized:
        Table / Fig / Fig. / Figure / Eq / Eq. / Equation
        → "table" / "figure" / "equation"

    Duplicates are de-duped while preserving first occurrence order so
    "Table 2 ... Table 2 ..." ranks Table 2 once.
    """
    refs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    if not content:
        return refs
    for match in _NARRATIVE_REF_RE.finditer(content):
        family = _normalize_family(match.group(1))
        number = match.group(2)
        key = (family, number)
        if key in seen:
            continue
        seen.add(key)
        refs.append(key)
    return refs


def _sibling_identifier(chunk: Mapping[str, Any]) -> tuple[str, str] | None:
    """Best-effort identifier from a sibling chunk's body.

    Looks at the start of the content (after metadata header brackets)
    and tries to pick out "Table N" / "Fig. N" first, then falls back to
    LaTeX ``\\tag{N}`` which is how marker labels equations / formulas.
    Returns None when nothing parseable is found.
    """
    content = str(chunk.get("content") or "")
    if not content:
        return None

    # Strip leading bracketed metadata so we look at the actual body.
    body = re.sub(r"^(?:\[[^\[\]]*\])+\n?", "", content, count=1)

    head_match = _SIBLING_ID_HEAD_RE.search(body[:240])
    if head_match is not None:
        family = _normalize_family(head_match.group(1))
        return (family, head_match.group(2))

    tag_match = _SIBLING_ID_TAG_RE.search(body[:240])
    if tag_match is not None:
        return ("equation", tag_match.group(1))

    return None


def _sibling_rank(
    chunk: Mapping[str, Any],
    anchor_refs: list[tuple[str, str]],
) -> tuple[int, int]:
    """Rank a candidate sibling against the anchor narrative's references.

    Lower is better. The first element is the position of the matching
    reference in ``anchor_refs`` (0 = first mention). The second element
    is the chunk_index, used as a stable tie-breaker so identical-rank
    siblings keep document order.

    When the chunk's identifier doesn't appear in anchor_refs at all
    (no literal mention), the sibling gets a sentinel rank that sorts
    AFTER every cited sibling — they ride in only on remaining capacity.
    """
    identifier = _sibling_identifier(chunk)
    chunk_index = chunk.get("chunk_index")
    tie = chunk_index if isinstance(chunk_index, int) else 0
    if identifier is None or identifier not in anchor_refs:
        return (10_000, tie)
    return (anchor_refs.index(identifier), tie)


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
    # section_title, page) so we can match them efficiently against all_chunks.
    # Also pull the anchor's content so we can rank candidate siblings by
    # literal cross-reference (Table N / Fig N / Eq N) mentions in the narrative.
    anchors: list[tuple[str, str, str, Any, str, list[tuple[str, str]]]] = []
    for item in final_results:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("chunk_type") or "") != "narrative":
            continue
        mat = _normalize_material_id(item.get("material_id"))
        sec = _normalize_section_key(item.get("section_path"))
        sec_title = str(item.get("section_title") or "").strip()
        page = item.get("page")
        anchor_id = str(item.get("chunk_id") or "")
        anchor_refs = _extract_narrative_refs(str(item.get("content") or ""))
        anchors.append((mat, sec, sec_title, page, anchor_id, anchor_refs))

    if not anchors:
        return []

    # Collect candidates first (no cap yet), then rank by literal
    # cross-reference order against the anchor that pulled them in.
    candidates: list[tuple[tuple[int, int], dict[str, Any]]] = []
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
        c_sec_title = str(chunk.get("section_title") or "").strip()
        c_page = chunk.get("page")

        for anchor_mat, anchor_sec, anchor_sec_title, anchor_page, anchor_id, anchor_refs in anchors:
            if anchor_mat and c_mat and anchor_mat != c_mat:
                continue
            # Resolution order: section_path > section_title > page.
            # section_path is marker's structural truth; section_title is
            # the next-best signal for legacy PyMuPDF chunks (which lack
            # section_path); same-page is a coarse last resort for chunks
            # with neither, but multi-column / spanning-page layouts make
            # it noisy, so it's gated on BOTH sides lacking title.
            #
            # When EITHER side has a section_path, it is the deciding
            # signal — we do NOT fall back to title when path is present
            # but mismatched, because path is finer-grained than title
            # (e.g. anchor "3.2. Mechanical properties" should never
            # bring in a table from "3.1. Microstructure" just because
            # both live under the broader "3. Results" title).
            either_has_path = bool(anchor_sec) or bool(c_sec)
            section_match = bool(anchor_sec) and anchor_sec == c_sec
            section_title_match = (
                not either_has_path
                and bool(anchor_sec_title)
                and anchor_sec_title == c_sec_title
            )
            page_match = (
                not section_match
                and not section_title_match
                and not anchor_sec_title
                and not c_sec_title
                and not either_has_path
                and anchor_page is not None
                and c_page is not None
                and anchor_page == c_page
            )
            if not (section_match or section_title_match or page_match):
                continue

            sib = dict(chunk)
            sib["sibling_anchor"] = anchor_id
            if section_match:
                sib["sibling_reason"] = "section_path"
            elif section_title_match:
                sib["sibling_reason"] = "section_title"
            else:
                sib["sibling_reason"] = "same_page"
            # Tag the chunk with a source label the chat layer's
            # ContextChunkPayload constructor copies through to the LLM
            # context payload. Lets the UI / prompt builder / answer
            # judge see "this chunk is a sibling, not a rerank hit".
            existing_labels = sib.get("source_labels")
            if isinstance(existing_labels, list):
                labels = list(existing_labels)
            else:
                labels = []
            if "structured_sibling" not in labels:
                labels.append("structured_sibling")
            sib["source_labels"] = labels
            # Source hint string for legacy single-string consumers.
            hint = str(sib.get("source_hint") or "").strip()
            sib["source_hint"] = (
                f"{hint}+structured_sibling" if hint else "structured_sibling"
            )
            rank = _sibling_rank(sib, anchor_refs)
            candidates.append((rank, sib))
            seen.add(cid)
            break  # one anchor per sibling is enough

    candidates.sort(key=lambda pair: pair[0])
    return [sib for _rank, sib in candidates[:max_siblings]]


def merge_with_siblings(
    final_results: Sequence[Mapping[str, Any]],
    siblings: Sequence[Mapping[str, Any]],
    *,
    total_cap: int,
) -> list[dict[str, Any]]:
    """Insert siblings IMMEDIATELY AFTER their anchor narrative.

    Why insert (not append):
        The downstream chat-router truncate loop walks ``results`` in
        order and stops when either ``max_chunks`` or ``max_chars`` is
        exhausted. If we appended siblings at the tail, they would be
        the first things dropped whenever narrative chunks ate the
        budget — which is the failure mode the e2e probe exposed
        (chunk_29 / chunk_31 lost their content to the char budget every
        single time). Inserting after the anchor guarantees the table /
        formula sibling sits next to the prose that motivated it, and
        gives the LLM a fighting chance of seeing the numerical row
        before the budget runs out.

    Capacity rules:
        - When ``len(base) + len(sibs) <= total_cap``: every sibling is
          inserted after its anchor; original order preserved otherwise.
        - When tight: the lowest-ranked NARRATIVE from the tail is
          dropped to make room for each sibling. Structured chunks
          already in ``base`` (presumed earned via rerank) are NEVER
          dropped.

    Returns:
        A new list of dict shallow copies. Length is at most
        ``total_cap``. Sibling dicts retain the ``sibling_anchor`` /
        ``sibling_reason`` fields added by ``select_structured_siblings``.

    Raises:
        ValueError: If ``total_cap`` is not a positive integer.
    """
    if not isinstance(total_cap, int) or total_cap <= 0:
        raise ValueError("total_cap must be a positive integer")

    base = [dict(item) for item in final_results if isinstance(item, Mapping)]
    sibs = [dict(item) for item in siblings if isinstance(item, Mapping)]
    if not sibs:
        return base[:total_cap]

    # Index base chunks by chunk_id so we can locate each sibling's anchor.
    base_index_by_id: dict[str, int] = {}
    for idx, item in enumerate(base):
        cid = str(item.get("chunk_id") or "")
        if cid:
            base_index_by_id[cid] = idx

    merged: list[dict[str, Any]] = list(base)

    def _drop_tail_narrative(items: list[dict[str, Any]]) -> bool:
        """Remove the lowest-ranked narrative from the tail; return True
        when something was dropped."""
        for idx in range(len(items) - 1, -1, -1):
            if str(items[idx].get("chunk_type") or "") == "narrative":
                items.pop(idx)
                return True
        return False

    for sib in sibs:
        anchor_id = str(sib.get("sibling_anchor") or "")
        # Locate anchor position fresh each iteration — earlier inserts
        # may have shifted indices.
        insert_at: int | None = None
        if anchor_id:
            for idx, item in enumerate(merged):
                if str(item.get("chunk_id") or "") == anchor_id:
                    insert_at = idx + 1
                    break
        if insert_at is None:
            insert_at = len(merged)  # anchor not found: tail-append fallback

        if len(merged) >= total_cap and not _drop_tail_narrative(merged):
            break  # nothing safe to drop; stop adding siblings.
        # Re-locate anchor after the drop (drop may have changed indices).
        if anchor_id:
            for idx, item in enumerate(merged):
                if str(item.get("chunk_id") or "") == anchor_id:
                    insert_at = idx + 1
                    break

        merged.insert(min(insert_at, len(merged)), sib)

    return merged[:total_cap]
