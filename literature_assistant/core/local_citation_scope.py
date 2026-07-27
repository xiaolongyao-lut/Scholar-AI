"""Bounded PDF-selection context and local cited-material matching.

The module is deliberately retrieval-agnostic: it only inspects already
ingested project chunks and bibliographic metadata. Callers decide how matched
material ids are searched and how the resulting evidence is rendered.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from difflib import SequenceMatcher
import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from literature_assistant.core.models import PdfBboxUnit, pdf_bbox_matches_unit
else:
    from models import PdfBboxUnit, pdf_bbox_matches_unit


_REFERENCE_SECTION_RE = re.compile(
    r"(?:^|\b)(references?|bibliography|works\s+cited)(?:\b|$)|参考文献|引用文献",
    re.IGNORECASE,
)
_REFERENCE_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\d+(?:\.\d+)*[.)、:]?\s*)?"
    r"(?:references?|bibliography|works\s+cited|参考文献|引用文献)\s*[:：]?\s*$",
    re.IGNORECASE,
)
_CHUNK_SECTION_PREFIX_RE = re.compile(
    r"\[(?:章节|section)\s*:\s*(?P<section>[^\]]+)\]",
    re.IGNORECASE,
)
_POST_REFERENCE_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\d+(?:\.\d+)*[.)、:]?\s*)?"
    r"(?:append(?:ix|ices)(?:\s+[A-Z0-9]+)?|acknowledg(?:e)?ments?|"
    r"credit\s+authorship\s+contribution\s+statement|author\s+contributions?|"
    r"declarations?|supplementary\s+(?:materials?|information)|"
    r"conflicts?\s+of\s+interest|competing\s+interests?|data\s+availability|funding)"
    r"\s*[:：]?\s*$",
    re.IGNORECASE,
)
_NUMERIC_CITATION_RE = re.compile(r"\[(?P<body>\d{1,4}(?:\s*[-–—,，;；]\s*\d{1,4})*)\]")
_NUMERIC_ENTRY_RE = re.compile(
    r"^\s*(?:\[(?P<bracket>\d{1,4})\]|(?P<plain>\d{1,3})[.)、])\s*(?P<body>.+)",
    re.DOTALL,
)
_NUMERIC_ENTRY_LABEL_RE = re.compile(
    r"^\s*(?:\[(?P<bracket>\d{1,4})\]|(?P<plain>\d{1,3})[.)、])\s*$"
)
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}[a-z]?\b", re.IGNORECASE)
_AUTHOR_YEAR_RE = re.compile(
    r"(?<![A-Za-zÀ-ÖØ-öø-ÿ])"
    r"(?P<author>[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,40})"
    r"(?:\s+(?i:et\s+al)\.)?"
    r"(?:\s*(?:,|&|(?i:and)|和)\s*[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,40})?"
    r"\s*[,，(（]\s*(?P<year>(?:19|20)\d{2}[a-z]?)",
)
_TOKEN_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)
_MAX_REFERENCE_SECTION_CHUNKS = 256
_MAX_REFERENCE_HEADING_LOOKBACK_CHUNKS = 8
_MAX_UNMARKED_REFERENCE_CONTINUATIONS = 1
_MIN_ANCHOR_TEXT_SIMILARITY = 0.35
_MIN_ANCHOR_BBOX_OVERLAP = 0.2
_MIN_ADJACENT_TEXT_SIMILARITY = 0.3
_MAX_CITATION_MARKERS_PER_SELECTION = 64

LocalCitationOutcome = Literal[
    "matched",
    "unmatched",
    "ambiguous",
    "over_limit",
    "failed",
]


@dataclass(frozen=True, slots=True)
class SelectionParagraphWindow:
    """One complete anchor paragraph plus at most one adjacent paragraph."""

    anchor_text: str
    adjacent_text: str | None
    anchor_chunk_id: str | None
    page: int | None

    @property
    def combined_text(self) -> str:
        """Return the bounded text used for local citation detection."""

        if self.adjacent_text:
            return f"{self.anchor_text}\n\n{self.adjacent_text}"
        return self.anchor_text


@dataclass(frozen=True, slots=True)
class LocalCitationMatch:
    """A unique project-material match for one local citation marker."""

    material_id: str
    material_title: str
    marker: str
    reference_text: str
    match_reason: str
    reference_chunk_id: str | None = None
    reference_page: int | None = None
    reference_bbox: tuple[float, float, float, float] | None = None
    reference_bbox_unit: PdfBboxUnit | None = None
    confidence: float | None = None
    reference_fingerprint: str | None = None
    target_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class LocalCitationMention:
    """One citation marker outcome, including non-match and limit reasons."""

    marker: str
    outcome: LocalCitationOutcome
    reason: str
    reference_text: str = ""
    reference_number: int | None = None
    reference_chunk_id: str | None = None
    reference_page: int | None = None
    reference_bbox: tuple[float, float, float, float] | None = None
    reference_bbox_unit: PdfBboxUnit | None = None
    target_material_id: str | None = None
    target_material_title: str | None = None
    match_reason: str | None = None
    confidence: float | None = None
    candidate_material_ids: tuple[str, ...] = ()
    reference_fingerprint: str | None = None
    target_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class LocalCitationResolution:
    """Resolved selection window and safely matched local cited materials."""

    window: SelectionParagraphWindow | None
    matches: tuple[LocalCitationMatch, ...] = ()
    mentions: tuple[LocalCitationMention, ...] = ()
    failure_reason: str | None = None

    @property
    def matched_material_ids(self) -> tuple[str, ...]:
        """Return stable unique material ids in citation order."""

        return tuple(match.material_id for match in self.matches)


@dataclass(frozen=True, slots=True)
class _Paragraph:
    text: str
    chunk_id: str | None
    page: int | None
    chunk_index: int
    paragraph_index: int
    bbox: tuple[float, float, float, float] | None
    bbox_unit: PdfBboxUnit | None
    section_title: str


@dataclass(frozen=True, slots=True)
class _ReferenceEntry:
    number: int | None
    text: str
    doi: str | None
    year: str | None
    chunk_id: str | None
    page: int | None
    bbox: tuple[float, float, float, float] | None
    bbox_unit: PdfBboxUnit | None
    source_fingerprint: str


@dataclass(frozen=True, slots=True)
class _ReferencePart:
    text: str
    chunk_id: str | None
    page: int | None
    bbox: tuple[float, float, float, float] | None
    bbox_unit: PdfBboxUnit | None
    source_fingerprint: str


def _clean_text(value: object, *, max_chars: int = 12000) -> str:
    text = str(value or "").replace("\x00", " ")
    return re.sub(r"[ \t]+", " ", text).strip()[:max_chars]


def _chunk_text(chunk: Mapping[str, Any]) -> str:
    for key in ("content", "raw_content", "text"):
        text = _clean_text(chunk.get(key))
        if text:
            return text
    return ""


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value.is_integer() and value > 0:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _reference_chunk_sort_key(chunk: Mapping[str, Any]) -> tuple[int, int]:
    """Return stable page/index ordering for a reference-section chunk."""

    raw_index = chunk.get("chunk_index")
    chunk_index = raw_index if isinstance(raw_index, int) else 1_000_000
    return _positive_int(chunk.get("page")) or 1_000_000, chunk_index


def _bbox_unit(value: object, *, has_bbox: bool) -> PdfBboxUnit | None:
    if not has_bbox:
        return None
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, PdfBboxUnit):
        return value
    if isinstance(value, str):
        try:
            return PdfBboxUnit(value.strip())
        except ValueError:
            return None
    return None


def _bbox(
    value: object,
    unit: PdfBboxUnit | None,
) -> tuple[float, float, float, float] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 4:
        return None
    parts: list[float] = []
    for item in value:
        if not isinstance(item, int | float) or isinstance(item, bool):
            return None
        parts.append(float(item))
    x, y, width, height = parts
    if width <= 0 or height <= 0:
        return None
    if unit is None or not pdf_bbox_matches_unit(parts, unit):
        return None
    return (x, y, width, height)


def _bbox_overlap(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    ix = max(0.0, min(lx + lw, rx + rw) - max(lx, rx))
    iy = max(0.0, min(ly + lh, ry + rh) - max(ly, ry))
    intersection = ix * iy
    if intersection <= 0:
        return 0.0
    return intersection / max(min(lw * lh, rw * rh), 1e-9)


def _normalize(value: object) -> str:
    raw = unicodedata.normalize("NFKD", _clean_text(value, max_chars=2000)).casefold()
    return " ".join(_TOKEN_RE.findall(raw))


def _tokens(value: object) -> set[str]:
    return {token for token in _normalize(value).split() if len(token) > 1}


def _text_similarity(left: object, right: object) -> float:
    a = _normalize(left)
    b = _normalize(right)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b)) + 0.5
    a_tokens = _tokens(a)
    b_tokens = _tokens(b)
    token_score = len(a_tokens & b_tokens) / max(len(a_tokens), 1)
    return max(token_score, SequenceMatcher(None, a, b).ratio())


def _stable_fingerprint(payload: object) -> str:
    """Return a deterministic content fingerprint without retaining raw paths."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _chunk_raw_text(chunk: Mapping[str, Any], *, max_chars: int = 8000) -> str:
    """Prefer parser text over provider-facing structured prefixes."""

    for key in ("raw_content", "equation_latex", "content", "text"):
        text = _clean_text(chunk.get(key), max_chars=max_chars)
        if text:
            return text
    return ""


def _string_values(value: object) -> tuple[str, ...]:
    """Return bounded non-empty identifiers from an untrusted list-like value."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    values: list[str] = []
    for item in value:
        normalized = _clean_text(item, max_chars=256)
        if normalized and normalized not in values:
            values.append(normalized)
        if len(values) >= 32:
            break
    return tuple(values)


def _structured_selection_window(
    chunks: Sequence[Mapping[str, Any]],
    *,
    material_id: str,
    page: int | None,
    selected_text: str | None,
    bbox: Sequence[float] | None,
    bbox_unit: PdfBboxUnit | str | None,
    selection_kind: str,
    chunk_id: str | None,
    candidate_id: str | None,
) -> SelectionParagraphWindow | None:
    """Resolve figure/table/formula objects before generic paragraph matching."""

    if selection_kind not in {"figure", "table", "formula"}:
        return None
    expected_types = {
        "figure": frozenset({"figure", "figure_caption", "image_caption"}),
        "table": frozenset({"table", "table_caption"}),
        "formula": frozenset({"formula", "equation"}),
    }[selection_kind]
    normalized_chunk_id = _clean_text(chunk_id, max_chars=256)
    normalized_candidate_id = _clean_text(candidate_id, max_chars=256)
    target_unit = _bbox_unit(bbox_unit, has_bbox=bbox is not None)
    target_bbox = _bbox(bbox, target_unit)
    selected = _clean_text(selected_text, max_chars=4000)
    ranked: list[tuple[float, int, Mapping[str, Any]]] = []

    for fallback_index, chunk in enumerate(chunks):
        if _clean_text(chunk.get("material_id"), max_chars=256) != material_id:
            continue
        text = _chunk_raw_text(chunk)
        if not text:
            continue
        candidate_chunk_id = _clean_text(chunk.get("chunk_id") or chunk.get("id"), max_chars=256)
        figure_id = _clean_text(chunk.get("figure_id"), max_chars=256)
        table_id = _clean_text(chunk.get("table_id"), max_chars=256)
        linked_ids = {
            *_string_values(chunk.get("linked_figure_ids")),
            *_string_values(chunk.get("linked_table_ids")),
        }
        direct_ids = {value for value in (candidate_chunk_id, figure_id, table_id) if value}
        chunk_type = _clean_text(chunk.get("chunk_type"), max_chars=64).casefold()
        chunk_page = _positive_int(chunk.get("page"))
        raw_bbox = chunk.get("bbox")
        chunk_unit = _bbox_unit(chunk.get("bbox_unit"), has_bbox=raw_bbox is not None)
        chunk_bbox = _bbox(raw_bbox, chunk_unit)
        overlap = 0.0
        if (
            target_bbox is not None
            and target_unit is not None
            and chunk_bbox is not None
            and chunk_unit == target_unit
            and (page is None or chunk_page == page)
        ):
            overlap = _bbox_overlap(target_bbox, chunk_bbox)

        exact_identity = bool(
            (normalized_chunk_id and normalized_chunk_id == candidate_chunk_id)
            or (normalized_candidate_id and normalized_candidate_id in direct_ids)
        )
        linked_identity = bool(normalized_candidate_id and normalized_candidate_id in linked_ids)
        type_match = chunk_type in expected_types
        text_similarity = _text_similarity(selected, text) if selected else 0.0
        if not (
            exact_identity
            or (type_match and overlap >= _MIN_ANCHOR_BBOX_OVERLAP)
            or (type_match and text_similarity >= _MIN_ANCHOR_TEXT_SIMILARITY)
        ):
            continue
        score = 0.0
        if exact_identity:
            score += 20.0
        if linked_identity:
            score += 3.0
        if type_match:
            score += 6.0
        if page is not None:
            score += 3.0 if chunk_page == page else -3.0
        score += 8.0 * overlap
        score += 4.0 * text_similarity
        chunk_index = chunk.get("chunk_index")
        ordering = chunk_index if isinstance(chunk_index, int) else fallback_index
        ranked.append((score, ordering, chunk))

    if not ranked:
        return None
    _, anchor_order, anchor_chunk = max(ranked, key=lambda item: (item[0], -item[1]))
    anchor_text = _chunk_raw_text(anchor_chunk)
    anchor_chunk_id = _clean_text(
        anchor_chunk.get("chunk_id") or anchor_chunk.get("id"),
        max_chars=256,
    ) or None
    anchor_page = _positive_int(anchor_chunk.get("page"))
    anchor_section = _clean_text(anchor_chunk.get("section_title"), max_chars=256).casefold()
    object_id = _clean_text(
        anchor_chunk.get("figure_id")
        if selection_kind == "figure"
        else anchor_chunk.get("table_id")
        if selection_kind == "table"
        else normalized_candidate_id or anchor_chunk_id,
        max_chars=256,
    )

    adjacent_candidates: list[tuple[float, int, str]] = []
    for fallback_index, chunk in enumerate(chunks):
        if chunk is anchor_chunk:
            continue
        if _clean_text(chunk.get("material_id"), max_chars=256) != material_id:
            continue
        chunk_type = _clean_text(chunk.get("chunk_type"), max_chars=64).casefold()
        if chunk_type in expected_types or _REFERENCE_SECTION_RE.search(
            _clean_text(chunk.get("section_title"), max_chars=256)
        ):
            continue
        text = _chunk_raw_text(chunk)
        if not text:
            continue
        chunk_page = _positive_int(chunk.get("page"))
        chunk_index = chunk.get("chunk_index")
        ordering = chunk_index if isinstance(chunk_index, int) else fallback_index
        adjacent_linked_ids = (
            _string_values(chunk.get("linked_figure_ids"))
            if selection_kind == "figure"
            else _string_values(chunk.get("linked_table_ids"))
            if selection_kind == "table"
            else ()
        )
        explicitly_linked = bool(object_id and object_id in adjacent_linked_ids)
        if selection_kind in {"figure", "table"} and not explicitly_linked and chunk_page != anchor_page:
            continue
        if selection_kind == "formula" and chunk_page != anchor_page:
            continue
        distance = abs(ordering - anchor_order)
        candidate_section = _clean_text(chunk.get("section_title"), max_chars=256).casefold()
        if not explicitly_linked and distance > 3:
            continue
        if (
            not explicitly_linked
            and anchor_section
            and candidate_section
            and candidate_section != anchor_section
        ):
            continue
        score = (10.0 if explicitly_linked else 0.0) + (3.0 if chunk_page == anchor_page else 0.0)
        score += 1.5 if extract_local_citation_markers(text) else 0.0
        score += _text_similarity(" ".join((selected, anchor_text)), text)
        score -= min(distance, 20) * 0.08
        adjacent_candidates.append((score, -distance, text[:8000]))

    adjacent = max(adjacent_candidates, key=lambda item: (item[0], item[1]))[2] if adjacent_candidates else None
    return SelectionParagraphWindow(
        anchor_text=anchor_text[:8000],
        adjacent_text=adjacent,
        anchor_chunk_id=anchor_chunk_id,
        page=anchor_page,
    )


def _paragraphs_for_material(
    chunks: Sequence[Mapping[str, Any]],
    material_id: str,
) -> list[_Paragraph]:
    paragraphs: list[_Paragraph] = []
    for fallback_index, chunk in enumerate(chunks):
        if _clean_text(chunk.get("material_id"), max_chars=256) != material_id:
            continue
        text = _chunk_text(chunk)
        if not text:
            continue
        raw_parts = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()] or [text]
        chunk_index = _positive_int(chunk.get("chunk_index"))
        if chunk_index is None:
            raw_index = chunk.get("chunk_index")
            chunk_index = int(raw_index) if isinstance(raw_index, int) and raw_index >= 0 else fallback_index
        raw_bbox = chunk.get("bbox")
        bbox_unit = _bbox_unit(chunk.get("bbox_unit"), has_bbox=raw_bbox is not None)
        paragraph_bbox = _bbox(raw_bbox, bbox_unit)
        for paragraph_index, part in enumerate(raw_parts):
            paragraphs.append(
                _Paragraph(
                    text=part[:8000],
                    chunk_id=_clean_text(chunk.get("chunk_id") or chunk.get("id"), max_chars=256) or None,
                    page=_positive_int(chunk.get("page")),
                    chunk_index=chunk_index,
                    paragraph_index=paragraph_index,
                    bbox=paragraph_bbox,
                    bbox_unit=bbox_unit if paragraph_bbox is not None else None,
                    section_title=_clean_text(chunk.get("section_title"), max_chars=256),
                )
            )
    paragraphs.sort(
        key=lambda item: (
            item.page if item.page is not None else 1_000_000,
            item.chunk_index,
            item.paragraph_index,
        )
    )
    return paragraphs


def build_selection_paragraph_window(
    chunks: Sequence[Mapping[str, Any]],
    *,
    material_id: str,
    page: int | None,
    selected_text: str | None,
    bbox: Sequence[float] | None,
    bbox_unit: PdfBboxUnit | str | None = None,
    query: str = "",
    selection_kind: str = "text",
    chunk_id: str | None = None,
    candidate_id: str | None = None,
) -> SelectionParagraphWindow | None:
    """Resolve the full selected paragraph and at most one adjacent paragraph.

    Args:
        chunks: Already ingested project chunks.
        material_id: Material containing the active PDF selection.
        page: One-based PDF page when available.
        selected_text: Browser text selection; may be absent for region capture.
        bbox: Selection rectangle ``[x, y, width, height]``.
        bbox_unit: Declared coordinate unit. Missing or unsupported values
            disable geometric matching instead of guessing a coordinate space.
        query: User question used only to break adjacent-paragraph ties.
        selection_kind: Selected object type. Figure, table and formula
            selections first resolve their structured object/caption chunk.
        chunk_id: Optional stable chunk locator from the PDF selection.
        candidate_id: Optional figure/table/formula candidate identity.

    Returns:
        A bounded paragraph window, or ``None`` when no material paragraph can
        be located. The function never expands beyond one immediate neighbor.
    """

    normalized_material_id = _clean_text(material_id, max_chars=256)
    if not normalized_material_id:
        raise ValueError("material_id must be non-empty")
    normalized_kind = _clean_text(selection_kind, max_chars=32).casefold() or "text"
    if normalized_kind not in {"text", "figure", "table", "formula", "region"}:
        raise ValueError("selection_kind must be text, figure, table, formula, or region")
    structured_window = _structured_selection_window(
        chunks,
        material_id=normalized_material_id,
        page=page,
        selected_text=selected_text,
        bbox=bbox,
        bbox_unit=bbox_unit,
        selection_kind=normalized_kind,
        chunk_id=chunk_id,
        candidate_id=candidate_id,
    )
    if structured_window is not None:
        return structured_window
    paragraphs = _paragraphs_for_material(chunks, normalized_material_id)
    if not paragraphs:
        return None
    target_bbox_unit = _bbox_unit(bbox_unit, has_bbox=bbox is not None)
    target_bbox = _bbox(bbox, target_bbox_unit)
    selected = _clean_text(selected_text, max_chars=4000)
    best_index = -1
    best_score = float("-inf")
    for index, paragraph in enumerate(paragraphs):
        score = 0.0
        text_similarity = _text_similarity(selected, paragraph.text) if selected else 0.0
        bbox_overlap = 0.0
        if page is not None:
            score += 3.0 if paragraph.page == page else -2.0
        if selected:
            score += 6.0 * text_similarity
        if (
            target_bbox is not None
            and target_bbox_unit is not None
            and paragraph.bbox is not None
            and paragraph.bbox_unit == target_bbox_unit
            and paragraph.page == page
        ):
            bbox_overlap = _bbox_overlap(target_bbox, paragraph.bbox)
            score += 5.0 * bbox_overlap
        if (
            text_similarity < _MIN_ANCHOR_TEXT_SIMILARITY
            and bbox_overlap < _MIN_ANCHOR_BBOX_OVERLAP
        ):
            continue
        if _REFERENCE_SECTION_RE.search(paragraph.section_title):
            score -= 1.5
        if score > best_score:
            best_score = score
            best_index = index
    if best_index < 0:
        return None

    anchor = paragraphs[best_index]
    adjacent_candidates: list[tuple[float, _Paragraph]] = []
    basis = " ".join(part for part in (selected, query, anchor.text) if part)
    for neighbor_index in (best_index - 1, best_index + 1):
        if neighbor_index < 0 or neighbor_index >= len(paragraphs):
            continue
        neighbor = paragraphs[neighbor_index]
        if _REFERENCE_SECTION_RE.search(neighbor.section_title) and not _REFERENCE_SECTION_RE.search(anchor.section_title):
            continue
        distance_penalty = 0.2 if neighbor.page != anchor.page else 0.0
        text_similarity = _text_similarity(basis, neighbor.text)
        if text_similarity < _MIN_ADJACENT_TEXT_SIMILARITY:
            continue
        citation_bonus = 0.35 if extract_local_citation_markers(neighbor.text) else 0.0
        score = text_similarity + citation_bonus - distance_penalty
        adjacent_candidates.append((score, neighbor))
    adjacent = max(adjacent_candidates, key=lambda item: item[0])[1] if adjacent_candidates else None
    return SelectionParagraphWindow(
        anchor_text=anchor.text,
        adjacent_text=adjacent.text if adjacent is not None else None,
        anchor_chunk_id=anchor.chunk_id,
        page=anchor.page,
    )


def _expand_numeric_body(body: str) -> list[int]:
    normalized = body.replace("，", ",").replace("；", ",").replace(";", ",")
    numbers: list[int] = []
    for part in normalized.split(","):
        token = part.strip()
        if not token:
            continue
        bounds = re.split(r"\s*[-–—]\s*", token, maxsplit=1)
        if len(bounds) == 2 and all(bound.isdigit() for bound in bounds):
            start, end = (int(bound) for bound in bounds)
            if 0 < start <= end <= 9999 and end - start <= 50:
                numbers.extend(range(start, end + 1))
        elif token.isdigit():
            number = int(token)
            if 0 < number <= 9999:
                numbers.append(number)
    return list(dict.fromkeys(numbers))


def extract_local_citation_markers(text: str) -> tuple[str, ...]:
    """Extract numeric and author-year citation markers from bounded text."""

    markers: list[str] = []
    for match in _NUMERIC_CITATION_RE.finditer(_clean_text(text, max_chars=16000)):
        for number in _expand_numeric_body(match.group("body")):
            marker = f"[{number}]"
            if marker not in markers:
                markers.append(marker)
    for match in _AUTHOR_YEAR_RE.finditer(_clean_text(text, max_chars=16000)):
        marker = f"{match.group('author')} {match.group('year')}"
        if marker not in markers:
            markers.append(marker)
    return tuple(markers)


def _is_reference_heading(value: object) -> bool:
    text = _clean_text(value, max_chars=512)
    return bool(text and _REFERENCE_HEADING_RE.fullmatch(text))


def _chunk_has_reference_heading(text: str, section: str) -> bool:
    if _is_reference_heading(section):
        return True
    prefix_match = _CHUNK_SECTION_PREFIX_RE.search(text[:512])
    if prefix_match and _is_reference_heading(prefix_match.group("section")):
        return True
    return any(_is_reference_heading(line) for line in text.splitlines()[:3])


def _chunk_has_post_reference_heading(text: str, section: str) -> bool:
    if _POST_REFERENCE_HEADING_RE.fullmatch(section):
        return True
    return any(
        _POST_REFERENCE_HEADING_RE.fullmatch(_clean_text(line, max_chars=512))
        for line in text.splitlines()[:3]
    )


def _looks_like_reference_chunk(text: str) -> bool:
    lines = [_clean_text(line, max_chars=3000) for line in text.splitlines()[:8]]
    if any(
        _NUMERIC_ENTRY_RE.match(line) or _NUMERIC_ENTRY_LABEL_RE.fullmatch(line)
        for line in lines
        if line
    ):
        return True
    sample = _clean_text(text, max_chars=3000)
    if _DOI_RE.search(sample) and _YEAR_RE.search(sample):
        return True
    first_content_line = next(
        (line for line in lines if line and not _CHUNK_SECTION_PREFIX_RE.search(line)),
        "",
    )
    return bool(
        first_content_line
        and re.match(r"^[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’-]+(?:\s|,)", first_content_line)
        and _YEAR_RE.search(sample)
    )


def _starts_new_section(section: str, reference_section: str) -> bool:
    if not section or _is_reference_heading(section):
        return False
    if reference_section and section.casefold() == reference_section.casefold():
        return False
    return True


def _normalize_reference_entry_text(value: object) -> str:
    text = _clean_text(value, max_chars=12000)
    if not text:
        return ""
    previous = ""
    while previous != text:
        previous = text
        text = re.sub(
            r"(10\.\d{4,9}/[-._;()/:A-Z0-9]*)\s*\n\s*(?=[A-Z0-9])",
            r"\1",
            text,
            flags=re.IGNORECASE,
        )
    text = re.sub(r"(?<=[A-Za-z])[-\u00ad]\s*\n\s*(?=[a-z])", "", text)
    return _clean_text(re.sub(r"\s*\n\s*", " ", text), max_chars=6000)


def _join_wrapped_doi_lines(value: object) -> str:
    """Join line breaks that occur inside a DOI before entry splitting."""

    text = str(value or "")
    previous = ""
    while previous != text:
        previous = text
        text = re.sub(
            r"(10\.\d{4,9}/[-._;()/:A-Z0-9]*)\s*\n\s*(?=[A-Z0-9])",
            r"\1",
            text,
            flags=re.IGNORECASE,
        )
    return text


def _reference_part(chunk: Mapping[str, Any], text: str) -> _ReferencePart:
    """Capture a reference-section text block with its source locator."""

    raw_bbox = chunk.get("bbox")
    bbox_unit = _bbox_unit(chunk.get("bbox_unit"), has_bbox=raw_bbox is not None)
    resolved_bbox = _bbox(raw_bbox, bbox_unit)
    fingerprint_payload = {
        "material_id": _clean_text(chunk.get("material_id"), max_chars=256),
        "chunk_id": _clean_text(chunk.get("chunk_id") or chunk.get("id"), max_chars=256),
        "page": _positive_int(chunk.get("page")),
        "chunk_index": chunk.get("chunk_index") if isinstance(chunk.get("chunk_index"), int) else None,
        "chunk_hash": _clean_text(chunk.get("chunk_hash"), max_chars=256),
        "content_hash": _clean_text(chunk.get("content_hash"), max_chars=256),
        "locator_hash": _clean_text(chunk.get("locator_hash"), max_chars=256),
        "hash_version": _clean_text(chunk.get("hash_version"), max_chars=128),
        "text": _normalize_reference_entry_text(text),
    }
    return _ReferencePart(
        text=text,
        chunk_id=_clean_text(chunk.get("chunk_id") or chunk.get("id"), max_chars=256) or None,
        page=_positive_int(chunk.get("page")),
        bbox=resolved_bbox,
        bbox_unit=bbox_unit if resolved_bbox is not None else None,
        source_fingerprint=_stable_fingerprint(fingerprint_payload),
    )


def _reference_entries(chunks: Sequence[Mapping[str, Any]], material_id: str) -> list[_ReferenceEntry]:
    reference_parts: list[_ReferencePart] = []
    inside_references = False
    reference_section = ""
    unmarked_continuations = 0
    ordered_chunks = sorted(
        (chunk for chunk in chunks if _clean_text(chunk.get("material_id"), max_chars=256) == material_id),
        key=_reference_chunk_sort_key,
    )
    for ordered_index, chunk in enumerate(ordered_chunks):
        text = _clean_text(chunk.get("raw_content")) or _chunk_text(chunk)
        section = _clean_text(chunk.get("section_title"), max_chars=256)
        has_heading = _chunk_has_reference_heading(text, section)
        if not inside_references:
            if not has_heading:
                continue
            heading_page = _positive_int(chunk.get("page"))
            if heading_page is not None:
                lookback_start = max(0, ordered_index - _MAX_REFERENCE_HEADING_LOOKBACK_CHUNKS)
                for prior_chunk in ordered_chunks[lookback_start:ordered_index]:
                    if _positive_int(prior_chunk.get("page")) != heading_page:
                        continue
                    prior_text = _clean_text(prior_chunk.get("raw_content")) or _chunk_text(prior_chunk)
                    if prior_text and _looks_like_reference_chunk(prior_text):
                        reference_parts.append(_reference_part(prior_chunk, prior_text))
            inside_references = True
            reference_section = section
        else:
            if len(reference_parts) >= _MAX_REFERENCE_SECTION_CHUNKS:
                break
            if _starts_new_section(section, reference_section) or _chunk_has_post_reference_heading(text, section):
                break
            if has_heading or _looks_like_reference_chunk(text):
                unmarked_continuations = 0
            elif unmarked_continuations < _MAX_UNMARKED_REFERENCE_CONTINUATIONS:
                unmarked_continuations += 1
            else:
                break
        if text:
            reference_parts.append(_reference_part(chunk, text))
    if not reference_parts:
        return []

    units: list[tuple[int | None, str, _ReferencePart, tuple[str, ...]]] = []
    current_number: int | None = None
    current_lines: list[str] = []
    current_part: _ReferencePart | None = None
    current_part_fingerprints: list[str] = []
    for part in reference_parts:
        block = _join_wrapped_doi_lines(part.text)
        for raw_line in re.split(
            r"\n\s*\n+|\n(?=\s*(?:\[\d{1,4}\](?:\s+|$)|\d{1,3}[.)、](?:\s+|$)|[A-ZÀ-ÖØ-Þ]))",
            block,
        ):
            line = _clean_text(raw_line, max_chars=5000)
            if not line or _REFERENCE_SECTION_RE.fullmatch(line.rstrip(":")):
                continue
            numeric = _NUMERIC_ENTRY_RE.match(line)
            if numeric:
                if current_lines and current_part is not None:
                    units.append(
                        (
                            current_number,
                            " ".join(current_lines),
                            current_part,
                            tuple(current_part_fingerprints),
                        )
                    )
                current_number = int(numeric.group("bracket") or numeric.group("plain"))
                current_lines = [numeric.group("body").strip()]
                current_part = part
                current_part_fingerprints = [part.source_fingerprint]
                continue
            numeric_label = _NUMERIC_ENTRY_LABEL_RE.fullmatch(line)
            if numeric_label:
                if current_lines and current_part is not None:
                    units.append(
                        (
                            current_number,
                            " ".join(current_lines),
                            current_part,
                            tuple(current_part_fingerprints),
                        )
                    )
                current_number = int(
                    numeric_label.group("bracket") or numeric_label.group("plain")
                )
                current_lines = []
                current_part = part
                current_part_fingerprints = [part.source_fingerprint]
                continue
            if current_lines or current_number is not None:
                current_lines.append(line)
                if part.source_fingerprint not in current_part_fingerprints:
                    current_part_fingerprints.append(part.source_fingerprint)
            else:
                units.append((None, line, part, (part.source_fingerprint,)))
    if current_lines and current_part is not None:
        units.append(
            (
                current_number,
                " ".join(current_lines),
                current_part,
                tuple(current_part_fingerprints),
            )
        )

    entries: list[_ReferenceEntry] = []
    for number, text, part, part_fingerprints in units:
        cleaned = _normalize_reference_entry_text(text)
        if not cleaned:
            continue
        doi_match = _DOI_RE.search(cleaned)
        year_match = _YEAR_RE.search(cleaned)
        entries.append(
            _ReferenceEntry(
                number=number,
                text=cleaned,
                doi=normalize_doi(doi_match.group(0)) if doi_match else None,
                year=year_match.group(0).casefold() if year_match else None,
                chunk_id=part.chunk_id,
                page=part.page,
                bbox=part.bbox,
                bbox_unit=part.bbox_unit,
                source_fingerprint=_stable_fingerprint(
                    {
                        "reference_text": cleaned,
                        "part_fingerprints": part_fingerprints,
                    }
                ),
            )
        )
    return entries


def normalize_doi(value: object) -> str:
    """Normalize a DOI for exact local comparison."""

    raw = _clean_text(value, max_chars=512).casefold()
    raw = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", raw)
    return raw.rstrip(".,;:)]}")


def _material_record(
    material: Mapping[str, Any],
) -> tuple[str, str, tuple[str, ...], Mapping[str, Any], str] | None:
    material_id = _clean_text(material.get("material_id"), max_chars=256)
    title = _clean_text(material.get("title"), max_chars=1000)
    title_en = _clean_text(material.get("title_en"), max_chars=1000)
    titles = tuple(dict.fromkeys(item for item in (title, title_en) if item))
    raw_metadata = material.get("metadata")
    metadata: Mapping[str, Any] = raw_metadata if isinstance(raw_metadata, Mapping) else {}
    if not material_id or not titles:
        return None
    fingerprint = _stable_fingerprint(
        {
            "material_id": material_id,
            "titles": titles,
            "metadata": metadata,
            "updated_at": _clean_text(material.get("updated_at"), max_chars=128),
            "source_fingerprint": _clean_text(material.get("source_fingerprint"), max_chars=256),
        }
    )
    return material_id, titles[0], titles, metadata, fingerprint


def _metadata_text(metadata: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _metadata_authors(metadata: Mapping[str, Any]) -> list[str]:
    raw = metadata.get("authors") or metadata.get("author")
    if isinstance(raw, str):
        return [part.strip() for part in re.split(r"[,;；]", raw) if part.strip()]
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return [_clean_text(item, max_chars=256) for item in raw if _clean_text(item, max_chars=256)]
    return []


def _material_year(metadata: Mapping[str, Any]) -> str | None:
    for key in ("year", "publication_date", "date", "issued"):
        match = _YEAR_RE.search(_clean_text(metadata.get(key), max_chars=256))
        if match:
            return match.group(0).casefold()
    return None


def _candidate_score(
    entry: _ReferenceEntry,
    titles: Sequence[str],
    metadata: Mapping[str, Any],
) -> tuple[float, str]:
    material_doi = normalize_doi(_metadata_text(metadata, "doi", "DOI"))
    if material_doi and entry.doi and material_doi == entry.doi:
        return 10.0, "doi"

    entry_tokens = _tokens(entry.text)
    best_title_score = 0.0
    best_title_coverage = 0.0
    for title in titles:
        title_tokens = _tokens(title)
        title_coverage = len(title_tokens & entry_tokens) / max(len(title_tokens), 1)
        title_similarity = _text_similarity(title, entry.text)
        best_title_coverage = max(best_title_coverage, title_coverage)
        if len(title_tokens) >= 4 and title_coverage >= 0.82:
            best_title_score = max(best_title_score, 7.0 + title_coverage)
        if len(title_tokens) >= 2 and title_similarity >= 0.9:
            best_title_score = max(best_title_score, 6.5 + title_similarity)
    if best_title_score > 0:
        return best_title_score, "title"

    year = _material_year(metadata)
    authors = _metadata_authors(metadata)
    surnames = {
        _normalize(author).split()[-1]
        for author in authors
        if _normalize(author).split()
    }
    entry_tokens_normalized = set(_normalize(entry.text).split())
    if year and entry.year == year and any(surname in entry_tokens_normalized for surname in surnames):
        return 4.0 + best_title_coverage, "author_year"
    return 0.0, ""


def _match_confidence(reason: str) -> float:
    """Map conservative identity methods to bounded candidate confidence."""

    return {
        "doi": 1.0,
        "title": 0.9,
        "author_year": 0.75,
    }.get(reason, 0.0)


def _mention_from_entry(
    *,
    marker: str,
    outcome: LocalCitationOutcome,
    reason: str,
    entry: _ReferenceEntry | None,
    target_material_id: str | None = None,
    target_material_title: str | None = None,
    match_reason: str | None = None,
    confidence: float | None = None,
    candidate_material_ids: Sequence[str] = (),
    target_fingerprint: str | None = None,
) -> LocalCitationMention:
    """Build one bounded outcome while retaining a concrete reference locator."""

    return LocalCitationMention(
        marker=marker,
        outcome=outcome,
        reason=reason,
        reference_text=entry.text[:1200] if entry is not None else "",
        reference_number=entry.number if entry is not None else None,
        reference_chunk_id=entry.chunk_id if entry is not None else None,
        reference_page=entry.page if entry is not None else None,
        reference_bbox=entry.bbox if entry is not None else None,
        reference_bbox_unit=entry.bbox_unit if entry is not None else None,
        target_material_id=target_material_id,
        target_material_title=target_material_title,
        match_reason=match_reason,
        confidence=confidence,
        candidate_material_ids=tuple(dict.fromkeys(candidate_material_ids))[:8],
        reference_fingerprint=entry.source_fingerprint if entry is not None else None,
        target_fingerprint=target_fingerprint,
    )


def resolve_local_citation_scope(
    chunks: Sequence[Mapping[str, Any]],
    materials: Sequence[Mapping[str, Any]],
    *,
    current_material_id: str,
    page: int | None,
    selected_text: str | None,
    bbox: Sequence[float] | None,
    bbox_unit: PdfBboxUnit | str | None = None,
    query: str = "",
    max_matches: int = 3,
    selection_kind: str = "text",
    chunk_id: str | None = None,
    candidate_id: str | None = None,
) -> LocalCitationResolution:
    """Resolve a local selection window and uniquely match cited materials.

    Matching is conservative and ordered by DOI, title, then author-year.
    Every extracted marker receives a structured outcome; only a unique match
    enters ``matches``. The current material is never returned as its own cited
    target, and no graph-wide expansion occurs.
    """

    if max_matches <= 0:
        raise ValueError("max_matches must be positive")
    window = build_selection_paragraph_window(
        chunks,
        material_id=current_material_id,
        page=page,
        selected_text=selected_text,
        bbox=bbox,
        bbox_unit=bbox_unit,
        query=query,
        selection_kind=selection_kind,
        chunk_id=chunk_id,
        candidate_id=candidate_id,
    )
    if window is None:
        return LocalCitationResolution(window=None, failure_reason="selection_window_not_found")
    extracted_markers = extract_local_citation_markers(window.combined_text)
    markers = extracted_markers[:_MAX_CITATION_MARKERS_PER_SELECTION]
    overflow_marker = (
        extracted_markers[_MAX_CITATION_MARKERS_PER_SELECTION]
        if len(extracted_markers) > _MAX_CITATION_MARKERS_PER_SELECTION
        else None
    )
    if not markers:
        return LocalCitationResolution(window=window)
    entries = _reference_entries(chunks, current_material_id)
    if not entries:
        missing_mentions = [
            _mention_from_entry(
                marker=marker,
                outcome="unmatched",
                reason="reference_section_not_found",
                entry=None,
            )
            for marker in markers
        ]
        if overflow_marker is not None:
            missing_mentions.append(
                _mention_from_entry(
                    marker=overflow_marker,
                    outcome="over_limit",
                    reason="selection_marker_limit",
                    entry=None,
                )
            )
        return LocalCitationResolution(
            window=window,
            mentions=tuple(missing_mentions),
        )

    material_records = [record for item in materials if (record := _material_record(item)) is not None]
    matches: list[LocalCitationMatch] = []
    mentions: list[LocalCitationMention] = []
    seen_materials: set[str] = set()
    for marker in markers:
        entry_candidates: list[_ReferenceEntry] = []
        numeric = re.fullmatch(r"\[(\d{1,4})\]", marker)
        if numeric:
            number = int(numeric.group(1))
            entry_candidates = [entry for entry in entries if entry.number == number]
        else:
            marker_parts = marker.rsplit(" ", 1)
            if len(marker_parts) == 2:
                surname = _normalize(marker_parts[0])
                year = marker_parts[1].casefold()
                entry_candidates = [
                    entry for entry in entries
                    if entry.year == year and surname and surname in _normalize(entry.text)
                ]
        if not entry_candidates:
            mentions.append(
                _mention_from_entry(
                    marker=marker,
                    outcome="unmatched",
                    reason="reference_entry_not_found",
                    entry=None,
                )
            )
            continue
        if len(entry_candidates) != 1:
            mentions.append(
                _mention_from_entry(
                    marker=marker,
                    outcome="ambiguous",
                    reason="reference_entry_ambiguous",
                    entry=entry_candidates[0],
                )
            )
            continue
        entry = entry_candidates[0]
        scored: list[tuple[float, str, str, str, str]] = []
        for material_id, title, titles, metadata, target_fingerprint in material_records:
            if material_id == current_material_id:
                continue
            score, reason = _candidate_score(entry, titles, metadata)
            if score > 0:
                scored.append((score, material_id, title, reason, target_fingerprint))
        scored.sort(key=lambda item: (-item[0], item[1]))
        if not scored:
            mentions.append(
                _mention_from_entry(
                    marker=marker,
                    outcome="unmatched",
                    reason="project_material_not_found",
                    entry=entry,
                )
            )
            continue
        best = scored[0]
        if len(scored) > 1 and best[0] - scored[1][0] < 0.75:
            mentions.append(
                _mention_from_entry(
                    marker=marker,
                    outcome="ambiguous",
                    reason="project_material_ambiguous",
                    entry=entry,
                    candidate_material_ids=[item[1] for item in scored],
                )
            )
            continue
        _, material_id, title, reason, target_fingerprint = best
        confidence = _match_confidence(reason)
        if material_id not in seen_materials and len(seen_materials) >= max_matches:
            mentions.append(
                _mention_from_entry(
                    marker=marker,
                    outcome="over_limit",
                    reason="selection_secondary_material_limit",
                    entry=entry,
                    target_material_id=material_id,
                    target_material_title=title,
                    match_reason=reason,
                    confidence=confidence,
                    target_fingerprint=target_fingerprint,
                )
            )
            continue
        mentions.append(
            _mention_from_entry(
                marker=marker,
                outcome="matched",
                reason="unique_project_material",
                entry=entry,
                target_material_id=material_id,
                target_material_title=title,
                match_reason=reason,
                confidence=confidence,
                target_fingerprint=target_fingerprint,
            )
        )
        if material_id in seen_materials:
            continue
        seen_materials.add(material_id)
        matches.append(
            LocalCitationMatch(
                material_id=material_id,
                material_title=title,
                marker=marker,
                reference_text=entry.text[:1200],
                match_reason=reason,
                reference_chunk_id=entry.chunk_id,
                reference_page=entry.page,
                reference_bbox=entry.bbox,
                reference_bbox_unit=entry.bbox_unit,
                confidence=confidence,
                reference_fingerprint=entry.source_fingerprint,
                target_fingerprint=target_fingerprint,
            )
        )
    if overflow_marker is not None:
        mentions.append(
            _mention_from_entry(
                marker=overflow_marker,
                outcome="over_limit",
                reason="selection_marker_limit",
                entry=None,
            )
        )
    return LocalCitationResolution(
        window=window,
        matches=tuple(matches),
        mentions=tuple(mentions),
    )


def limit_local_citation_resolutions(
    resolutions: Sequence[LocalCitationResolution],
    *,
    max_secondary_materials: int = 3,
) -> tuple[LocalCitationResolution, ...]:
    """Apply one stable unique-material limit across all selections in a turn.

    Args:
        resolutions: Ordered per-selection resolution records from one project
            snapshot.
        max_secondary_materials: Maximum unique cited project materials that
            may enter immediate retrieval and candidate generation.

    Returns:
        Ordered copies with over-limit matches removed and their mention
        outcomes retained as ``over_limit``.
    """

    if max_secondary_materials <= 0:
        raise ValueError("max_secondary_materials must be positive")
    allowed_materials: list[str] = []
    limited: list[LocalCitationResolution] = []
    for resolution in resolutions:
        mentions: list[LocalCitationMention] = []
        for mention in resolution.mentions:
            material_id = mention.target_material_id
            if mention.outcome != "matched" or not material_id:
                mentions.append(mention)
                continue
            if material_id in allowed_materials:
                mentions.append(mention)
                continue
            if len(allowed_materials) < max_secondary_materials:
                allowed_materials.append(material_id)
                mentions.append(mention)
                continue
            mentions.append(
                replace(
                    mention,
                    outcome="over_limit",
                    reason="turn_secondary_material_limit",
                )
            )

        matches: list[LocalCitationMatch] = []
        for match in resolution.matches:
            if match.material_id in allowed_materials:
                matches.append(match)
                continue
            if not resolution.mentions and len(allowed_materials) < max_secondary_materials:
                allowed_materials.append(match.material_id)
                matches.append(match)
        limited.append(
            replace(
                resolution,
                matches=tuple(matches),
                mentions=tuple(mentions),
            )
        )
    return tuple(limited)
