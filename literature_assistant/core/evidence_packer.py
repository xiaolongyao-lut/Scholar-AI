from __future__ import annotations

from typing import Any, Optional, TypedDict, Union

try:
    from typing import NotRequired
except ImportError:  # pragma: no cover - Python 3.8 compatibility
    from typing_extensions import NotRequired

from text_utils import cjk_aware_tokenize
from token_utils import count_tokens


class EvidenceReference(TypedDict):
    """Machine-readable provenance carried from retrieval into answer artifacts."""

    chunk_id: str
    material_id: str
    text: str
    compressed_text: str
    quote: str
    label: str
    score: NotRequired[Union[float, str]]
    page: NotRequired[Union[int, str]]
    source: NotRequired[str]
    source_label: NotRequired[str]
    source_labels: NotRequired[list[str]]
    source_hint: NotRequired[str]
    rank: NotRequired[int]
    query_overlap_tokens: NotRequired[list[str]]


def _get_text(candidate: dict[str, Any]) -> str:
    return str(
        candidate.get("text")
        or candidate.get("content")
        or candidate.get("source_text")
        or candidate.get("claim")
        or ""
    ).strip()


def _get_compressed_text(candidate: dict[str, Any]) -> str:
    return str(candidate.get("compressed_text") or "").strip()


def _get_quote(candidate: dict[str, Any]) -> str:
    return str(candidate.get("quote") or "").strip()


def _get_label(candidate: dict[str, Any]) -> str:
    return str(candidate.get("label") or "").strip()


def _get_source_label(candidate: dict[str, Any]) -> str:
    return str(candidate.get("source_label") or candidate.get("source_hint") or "").strip()


def _get_source_labels(candidate: dict[str, Any]) -> list[str]:
    raw_labels = candidate.get("source_labels")
    if isinstance(raw_labels, list):
        return [str(label).strip() for label in raw_labels if str(label).strip()]
    source_label = _get_source_label(candidate)
    return [source_label] if source_label else []


def _get_score(candidate: dict[str, Any]) -> str:
    score = candidate.get("score")
    if score is None:
        return ""
    try:
        return f"{float(score):.4f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(score).strip()


def _get_chunk_id(candidate: dict[str, Any]) -> str:
    chunk_id = str(candidate.get("chunk_id") or "").strip()
    if chunk_id:
        return chunk_id
    material_id = str(candidate.get("material_id") or "unknown").strip() or "unknown"
    chunk_index = candidate.get("chunk_index")
    return f"{material_id}#{chunk_index if chunk_index is not None else 0}"


def _get_material_id(candidate: dict[str, Any]) -> str:
    material_id = str(candidate.get("material_id") or "").strip()
    if material_id:
        return material_id
    return _get_chunk_id(candidate)


def _coerce_score_value(value: Any) -> Optional[Union[float, str]]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        return text if text else None


def _coerce_page_value(value: Any) -> Optional[Union[int, str]]:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return text


def build_evidence_reference(
    candidate: dict[str, Any],
    *,
    rank: Optional[int] = None,
    query_tokens: Optional[set[str]] = None,
) -> EvidenceReference:
    """Return a stable evidence reference for JSON artifacts and UI consumers.

    Args:
        candidate: Retrieval or compression candidate containing at least text,
            compressed_text, quote, or source text. Missing chunk IDs are filled
            with the same deterministic fallback used by prompt rendering.
        rank: 0-indexed position in the final evidence list.
        query_tokens: Lowercased query tokens for overlap computation.

    Returns:
        A JSON-serializable provenance record that keeps chunk identity, material
        identity, score, label, quote, and compressed text together.
    """
    if not isinstance(candidate, dict):
        raise TypeError("candidate must be a mapping")

    text = _get_text(candidate)
    compressed_text = _get_compressed_text(candidate)
    reference: EvidenceReference = {
        "chunk_id": _get_chunk_id(candidate),
        "material_id": _get_material_id(candidate),
        "text": text,
        "compressed_text": compressed_text,
        "quote": _get_quote(candidate),
        "label": _get_label(candidate),
    }

    score = _coerce_score_value(candidate.get("score"))
    if score is not None:
        reference["score"] = score

    page = _coerce_page_value(candidate.get("page"))
    if page is not None:
        reference["page"] = page

    source = str(candidate.get("source") or "").strip()
    if source:
        reference["source"] = source

    source_label = _get_source_label(candidate)
    if source_label:
        reference["source_label"] = source_label
        reference["source_hint"] = source_label

    source_labels = _get_source_labels(candidate)
    if source_labels:
        reference["source_labels"] = source_labels

    if rank is not None:
        reference["rank"] = rank

    if query_tokens:
        evidence_tokens = _token_set(compressed_text or text)
        overlap = sorted(query_tokens & evidence_tokens)
        if overlap:
            reference["query_overlap_tokens"] = overlap

    return reference


def build_evidence_references(
    candidates: list[dict[str, Any]],
    *,
    query_tokens: Optional[set[str]] = None,
) -> list[EvidenceReference]:
    """Build JSON-safe provenance records for packed evidence candidates."""
    if not isinstance(candidates, list):
        raise TypeError("candidates must be a list")
    return [
        build_evidence_reference(candidate, rank=idx, query_tokens=query_tokens)
        for idx, candidate in enumerate(candidates)
    ]


def format_evidence_item(candidate: dict[str, Any], *, rank: Optional[int] = None) -> str:
    # Preserve retrieval/compression provenance so downstream prompts can
    # require real [chunk_id], quotes, and compressed evidence consistently.
    chunk_id = _get_chunk_id(candidate)
    material_id = _get_material_id(candidate)
    text = _get_compressed_text(candidate) or _get_text(candidate)
    quote = _get_quote(candidate)
    label = _get_label(candidate)
    score = _get_score(candidate)
    source_labels = _get_source_labels(candidate)

    lines = [
        "--- EVIDENCE_START ---",
        f"SOURCE_ID: [{chunk_id}]",
        f"MATERIAL: {material_id}",
    ]
    if score:
        lines.append(f"SCORE: {score}")
    if label:
        lines.append(f"LABEL: {label}")
    if rank is not None:
        lines.append(f"RANK: {rank}")
    if source_labels:
        lines.append(f"SOURCE_LABELS: {', '.join(source_labels)}")
    if quote:
        lines.append(f"QUOTE: {quote}")
    lines.append(f"BODY: {text}")
    lines.append("--- EVIDENCE_END ---")

    return "\n".join(lines).strip()


def _token_cost(candidate: dict[str, Any]) -> int:
    text = _get_compressed_text(candidate) or _get_text(candidate)
    return count_tokens(text)


def _token_set(text: str) -> set[str]:
    lowered = text.lower().strip()
    if not lowered:
        return set()
    return {token for token in cjk_aware_tokenize(lowered) if token}


def _jaccard_similarity(left: str, right: str) -> float:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens & right_tokens
    union = left_tokens | right_tokens
    return len(overlap) / len(union)


def _sorted_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        candidates,
        key=lambda candidate: float(candidate.get("score") or 0.0),
        reverse=True,
    )


def _apply_same_material_hard_dedupe(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    texts_by_material: dict[str, list[str]] = {}
    for candidate in candidates:
        material_id = _get_material_id(candidate)
        text = _get_text(candidate)
        prior_texts = texts_by_material.setdefault(material_id, [])
        if any(_jaccard_similarity(text, prior_text) > 0.9 for prior_text in prior_texts):
            continue
        kept.append(candidate)
        prior_texts.append(text)
    return kept


def _trim_same_material_redundancy_when_over_budget(
    candidates: list[dict[str, Any]],
    *,
    budget_tokens: int,
) -> list[dict[str, Any]]:
    if sum(_token_cost(candidate) for candidate in candidates) <= budget_tokens:
        return candidates

    kept: list[dict[str, Any]] = []
    texts_by_material: dict[str, list[str]] = {}
    for candidate in candidates:
        material_id = _get_material_id(candidate)
        text = _get_text(candidate)
        prior_texts = texts_by_material.setdefault(material_id, [])
        if any(_jaccard_similarity(text, prior_text) > 0.7 for prior_text in prior_texts):
            continue
        kept.append(candidate)
        prior_texts.append(text)
    return kept


def pack_evidence(
    candidates: list[dict[str, Any]],
    *,
    budget_tokens: int,
    hard_cap_tokens: int,
    max_per_material: int,
    top_k: int,
) -> list[dict[str, Any]]:
    if budget_tokens <= 0 or hard_cap_tokens <= 0 or max_per_material <= 0 or top_k <= 0:
        return []

    ordered = _apply_same_material_hard_dedupe(_sorted_candidates(list(candidates)))

    packed: list[dict[str, Any]] = []
    material_counts: dict[str, int] = {}
    for candidate in ordered:
        if len(packed) >= top_k:
            break
        material_id = _get_material_id(candidate)
        if material_counts.get(material_id, 0) >= max_per_material:
            continue
        if _token_cost(candidate) > budget_tokens:
            continue
        packed.append(candidate)
        material_counts[material_id] = material_counts.get(material_id, 0) + 1

    packed = _trim_same_material_redundancy_when_over_budget(
        packed,
        budget_tokens=budget_tokens,
    )

    while packed and sum(_token_cost(candidate) for candidate in packed) > hard_cap_tokens:
        packed.pop()

    return packed
