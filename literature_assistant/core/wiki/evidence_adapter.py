from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from literature_assistant.core.models.evidence import (
    PDF_URL_BBOX_UNIT,
    PdfBboxUnit,
    coerce_pdf_bbox,
    pdf_bbox_matches_unit,
)
from literature_assistant.core.wiki.source_registry import WikiRegistry


@dataclass(frozen=True)
class NormalizedEvidence:
    chunk_id: str | None
    source_id: str | None
    text: str
    material_id: str | None = None
    quote: str | None = None
    page: str | int | None = None
    rank: int | None = None
    source_labels: list[str] | None = None
    query_overlap_tokens: int | None = None
    bbox: list[float] | None = None
    bbox_unit: str | None = None


def _read_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_text_or_number(value: Any) -> str | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    return _read_text(value)


def _read_text_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    labels: list[str] = []
    for item in value:
        label = _read_text(item)
        if label and label not in labels:
            labels.append(label)
    return labels or None


def _read_bbox_unit(value: Any, bbox: list[float] | None) -> str | None:
    if bbox is None:
        return None
    if value is None:
        return PDF_URL_BBOX_UNIT.value if pdf_bbox_matches_unit(bbox, PDF_URL_BBOX_UNIT) else None
    try:
        unit = PdfBboxUnit(str(value))
    except ValueError:
        return None
    return unit.value if pdf_bbox_matches_unit(bbox, unit) else None


def coerce_evidence_reference(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "__dict__"):
        return vars(raw)
    if hasattr(raw, "_asdict"):
        return raw._asdict()
    raise TypeError(f"Cannot coerce {type(raw)} to evidence reference")


def normalize_evidence(raw: Any) -> NormalizedEvidence:
    evidence = coerce_evidence_reference(raw)
    chunk_id = _read_text(evidence.get("chunk_id"))
    material_id = _read_text(evidence.get("material_id"))
    source_id = _read_text(evidence.get("source_id"))
    text = _read_text(evidence.get("text")) or _read_text(evidence.get("compressed_text")) or _read_text(evidence.get("compressed")) or ""
    quote = _read_text(evidence.get("quote"))
    page = _read_text_or_number(evidence.get("page"))
    rank = evidence.get("rank")
    source_labels = _read_text_list(evidence.get("source_labels"))
    query_overlap_tokens = evidence.get("query_overlap_tokens")
    bbox = coerce_pdf_bbox(evidence.get("bbox"))
    bbox_unit = _read_bbox_unit(evidence.get("bbox_unit"), bbox)
    return NormalizedEvidence(
        chunk_id=chunk_id,
        source_id=source_id,
        text=text,
        material_id=material_id,
        quote=quote,
        page=page,
        rank=rank,
        source_labels=source_labels,
        query_overlap_tokens=query_overlap_tokens,
        bbox=bbox if bbox_unit is not None else None,
        bbox_unit=bbox_unit,
    )


def lookup_source_for_evidence(
    evidence: NormalizedEvidence,
    registry: WikiRegistry,
) -> str | None:
    if evidence.chunk_id and registry.verify_chunk_exists(evidence.chunk_id):
        return evidence.chunk_id
    if evidence.source_id:
        source = registry.get_source(evidence.source_id)
        if source:
            return evidence.source_id
    if evidence.material_id:
        source = registry.get_source(evidence.material_id)
        if source:
            return evidence.material_id
    return None


def render_citation(evidence: NormalizedEvidence) -> str:
    if evidence.chunk_id:
        return f"[{evidence.chunk_id}]"
    if evidence.source_id:
        if evidence.page:
            return f"[[{evidence.source_id}#page-{evidence.page}]]"
        return f"[[{evidence.source_id}]]"
    if evidence.material_id:
        if evidence.page:
            return f"[[{evidence.material_id}#page-{evidence.page}]]"
        return f"[[{evidence.material_id}]]"
    return ""


def evidence_to_wiki_citation(
    raw: Any,
    registry: WikiRegistry,
    *,
    fallback_mode: str = "draft",
) -> tuple[str, bool]:
    evidence = normalize_evidence(raw)
    target = lookup_source_for_evidence(evidence, registry)
    if not target:
        if fallback_mode == "draft":
            return "", False
        raise ValueError(f"Evidence target not found in registry: {evidence}")
    citation = render_citation(evidence)
    return citation, True


def parse_prompt_evidence(prompt_line: str) -> dict[str, str]:
    if not isinstance(prompt_line, str):
        raise TypeError("prompt_line must be a string")
    parts = prompt_line.split("/")
    if len(parts) < 2:
        raise ValueError("Invalid prompt evidence format")
    result: dict[str, str] = {}
    for i, part in enumerate(parts):
        if i == 0:
            result["source_id"] = part.strip()
        elif "MATERIAL" in part.upper():
            result["material_id"] = part.split(":")[-1].strip()
        elif "QUOTE" in part.upper():
            result["quote"] = part.split(":", 1)[-1].strip()
        elif "BODY" in part.upper():
            result["body"] = part.split(":", 1)[-1].strip()
    return result


def coerce_evidence_refs(raw_refs: Any) -> tuple[dict[str, Any], ...]:
    """Coerce raw evidence references to normalized tuple of dicts (LMWR-299).

    Accepts:
      - list/tuple of dicts
      - list/tuple of objects with __dict__ or _asdict()
      - single dict or object (wrapped in tuple)

    Raises ValueError if empty or cannot coerce.
    """
    if raw_refs is None:
        raise ValueError("raw_refs cannot be None")

    # Normalize to list
    if isinstance(raw_refs, (list, tuple)):
        items = list(raw_refs)
    else:
        items = [raw_refs]

    if not items:
        raise ValueError("at least one evidence reference is required")

    refs: list[dict[str, Any]] = []
    for raw in items:
        if isinstance(raw, dict):
            refs.append(raw)
        elif hasattr(raw, "__dict__"):
            refs.append(vars(raw))
        elif hasattr(raw, "_asdict"):
            refs.append(raw._asdict())
        else:
            raise TypeError(f"Cannot coerce {type(raw)} to evidence reference")

    return tuple(refs)


def evidence_ref_to_markdown(ref: dict[str, Any]) -> str:
    """Render evidence reference as markdown citation (LMWR-300).

    Uses quote > compressed_text > text for citation body.
    Raises ValueError if no quotable text found.
    """
    quote = ref.get("quote") or ref.get("compressed_text") or ref.get("text", "")
    if not quote or not str(quote).strip():
        raise ValueError("evidence reference has no quotable text")

    # Build citation target: prefer source_id, fallback to chunk_id
    target = ref.get("source_id") or ref.get("chunk_id") or ref.get("material_id") or "unknown"
    page = ref.get("page")
    if page and not ref.get("chunk_id"):
        target = f"{target}#page-{page}"
    return f"{str(quote).strip()} [[{target}]]"


def build_synthesis_body(question: str, answer: str, refs: tuple[dict[str, Any], ...]) -> str:
    """Build markdown body for synthesis/exploration page (LMWR-301).

    Args:
        question: Query question (becomes H1)
        answer: Answer text
        refs: Tuple of evidence references

    Returns:
        Markdown body with question, answer, and evidence section.

    Raises ValueError if question/answer empty or no refs.
    """
    question = question.strip()
    answer = answer.strip()
    if not question:
        raise ValueError("question cannot be empty")
    if not answer:
        raise ValueError("answer cannot be empty")
    if not refs:
        raise ValueError("synthesis requires evidence references")

    evidence_lines = "\n".join(f"- {evidence_ref_to_markdown(ref)}" for ref in refs)
    return f"# {question}\n\n{answer}\n\n## Evidence\n\n{evidence_lines}\n"


def last_answer_to_synthesis_draft(
    last_answer: Mapping[str, Any],
    registry: WikiRegistry,
) -> dict[str, Any]:
    if not isinstance(last_answer, Mapping):
        raise TypeError("last_answer must be a mapping")
    question = last_answer.get("query") or last_answer.get("question", "")
    answer = last_answer.get("answer", "")
    evidence_refs = last_answer.get("evidence_refs", [])
    citations: list[str] = []
    for ref in evidence_refs:
        citation, found = evidence_to_wiki_citation(ref, registry, fallback_mode="draft")
        if found and citation:
            citations.append(citation)
    body = f"{answer}\n\n## Evidence\n\n" + "\n".join(f"- {cit}" for cit in citations)
    frontmatter = {
        "id": f"synthesis-{hash(question) & 0xFFFFFFFF:08x}",
        "kind": "synthesis",
        "title": question[:100],
        "status": "draft",
    }
    return {"frontmatter": frontmatter, "body": body}
