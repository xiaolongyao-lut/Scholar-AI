from __future__ import annotations

import re
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
    bbox: NotRequired[list[float]]
    bbox_unit: NotRequired[str]
    figure_candidate: NotRequired[str]
    figure_candidate_detail: NotRequired[dict[str, Any]]
    image_paths: NotRequired[list[str]]


_QUOTE_MAX_CHARS = 320
_QUOTE_SENTENCE_BOUNDARY = re.compile(
    r"(?<=[.!?。！？])(?:\s+|$)|(?:\r?\n[^\S\r\n]*){2,}"
)
_PDF_BBOX_UNITS = {
    "normalized_ratio",
    "normalized_1000",
    "pdf_points",
    "css_pixels",
}


def _get_text(candidate: dict[str, Any]) -> str:
    return str(
        candidate.get("raw_content")
        or candidate.get("text")
        or candidate.get("content")
        or candidate.get("source_text")
        or candidate.get("claim")
        or ""
    ).strip()


def _get_compressed_text(candidate: dict[str, Any]) -> str:
    return str(candidate.get("compressed_text") or "").strip()


def _bounded_verbatim_quote(text: str, query_tokens: set[str]) -> str:
    """Return a source substring bounded around a query-token occurrence."""

    stripped = text.strip()
    if len(stripped) <= _QUOTE_MAX_CHARS:
        return stripped

    lowered = stripped.casefold()
    positions = [
        position
        for token in sorted(query_tokens, key=len, reverse=True)
        if token
        for position in [lowered.find(token.casefold())]
        if position >= 0
    ]
    anchor = min(positions) if positions else 0
    start = max(0, anchor - (_QUOTE_MAX_CHARS // 4))
    end = min(len(stripped), start + _QUOTE_MAX_CHARS)
    start = max(0, end - _QUOTE_MAX_CHARS)
    return stripped[start:end].strip()


def _select_query_quote(text: str, query_tokens: Optional[set[str]]) -> str:
    """Select a verbatim source sentence only when the query supports it."""

    normalized_query = {
        str(token).strip().casefold()
        for token in (query_tokens or set())
        if str(token).strip()
    }
    if not text.strip() or not normalized_query:
        return ""

    best_segment = ""
    best_overlap = 0
    for segment in _QUOTE_SENTENCE_BOUNDARY.split(text):
        candidate = segment.strip()
        if not candidate:
            continue
        overlap = len(normalized_query & _token_set(candidate))
        if overlap > best_overlap:
            best_segment = candidate
            best_overlap = overlap

    if best_overlap <= 0:
        return ""
    return _bounded_verbatim_quote(best_segment, normalized_query)


def _get_quote(
    candidate: dict[str, Any],
    *,
    query_tokens: Optional[set[str]] = None,
) -> str:
    explicit_quote = str(candidate.get("quote") or "").strip()
    if explicit_quote:
        return explicit_quote
    return _select_query_quote(_get_text(candidate), query_tokens)


def _coerce_bbox(value: Any) -> Optional[list[float]]:
    if not isinstance(value, list) or len(value) != 4:
        return None
    bbox: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        number = float(item)
        if number != number or number in (float("inf"), float("-inf")):
            return None
        bbox.append(number)
    return bbox


def _bbox_matches_unit(bbox: list[float], unit: str) -> bool:
    if unit == "normalized_ratio":
        x, y, width, height = bbox
        return (
            x >= 0.0
            and y >= 0.0
            and width > 0.0
            and height > 0.0
            and x <= 1.0
            and y <= 1.0
            and x + width <= 1.0001
            and y + height <= 1.0001
        )
    if unit == "normalized_1000":
        return all(0.0 <= item <= 1000.0 for item in bbox)
    if unit in {"pdf_points", "css_pixels"}:
        return all(item >= 0.0 for item in bbox)
    return False


def _coerce_bbox_anchor(
    bbox_value: Any,
    unit_value: Any,
) -> Optional[tuple[list[float], str]]:
    bbox = _coerce_bbox(bbox_value)
    if bbox is None:
        return None
    unit = str(unit_value or "normalized_ratio").strip()
    if unit not in _PDF_BBOX_UNITS or not _bbox_matches_unit(bbox, unit):
        return None
    return bbox, unit


def _coerce_image_paths(value: Any, *, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    paths: list[str] = []
    for item in value:
        path = str(item or "").strip()
        if not path or path in paths:
            continue
        paths.append(path[:260])
        if len(paths) >= limit:
            break
    return paths


def _coerce_figure_candidate_detail(value: Any) -> Optional[dict[str, Any]]:
    if not isinstance(value, dict):
        return None

    allowed_text_keys = {
        "id",
        "figure_id",
        "kind",
        "label",
        "caption",
        "chunk_id",
        "asset_path",
        "source",
    }
    detail: dict[str, Any] = {}
    for key in allowed_text_keys:
        cleaned = str(value.get(key) or "").strip()
        if cleaned:
            detail[key] = cleaned[:320]

    page = value.get("page")
    if isinstance(page, int) and not isinstance(page, bool) and page > 0:
        detail["page"] = page

    image_paths = _coerce_image_paths(value.get("image_paths"), limit=4)
    if image_paths:
        detail["image_paths"] = image_paths

    anchor = _coerce_bbox_anchor(value.get("bbox"), value.get("bbox_unit"))
    if anchor is not None:
        detail["bbox"], detail["bbox_unit"] = anchor
    return detail or None


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
        "quote": _get_quote(candidate, query_tokens=query_tokens),
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

    anchor = _coerce_bbox_anchor(candidate.get("bbox"), candidate.get("bbox_unit"))
    if anchor is not None:
        reference["bbox"], reference["bbox_unit"] = anchor

    figure_candidate = str(candidate.get("figure_candidate") or "").strip()
    if figure_candidate:
        reference["figure_candidate"] = figure_candidate[:260]

    figure_candidate_detail = _coerce_figure_candidate_detail(
        candidate.get("figure_candidate_detail")
    )
    if figure_candidate_detail is not None:
        reference["figure_candidate_detail"] = figure_candidate_detail

    image_paths = _coerce_image_paths(candidate.get("image_paths"))
    if image_paths:
        reference["image_paths"] = image_paths

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
