# -*- coding: utf-8 -*-
"""Pure project-export builder helpers (Phase 2)."""

from __future__ import annotations

import re
from typing import Any, Mapping


__all__ = [
    "ProjectExportFormat",
    "_strip_citation_tokens",
    "_shorten_export_text",
    "_material_excerpt",
    "_paragraphs_with_offsets",
    "_build_project_academic_export",
    "_markdown_table_cell",
]


class ProjectExportFormat(str, __import__("enum").Enum):
    MARKDOWN = "markdown"
    JSON = "json"


def _strip_citation_tokens(value: str) -> str:
    return re.sub(r"\[\^([^\]]+)\]", "", value).replace("\n", " ").strip()


def _shorten_export_text(value: str, max_length: int = 180) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 1].rstrip()}…"


def _material_excerpt(material: Any) -> str:
    focus_points = getattr(material, "focus_points", None) or []
    return str(
        getattr(material, "summary", "")
        or (focus_points[0] if focus_points else "")
        or getattr(material, "title", "")
    ).strip()


def _paragraphs_with_offsets(content: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    separator = re.compile(r"\n\s*\n+")
    last_index = 0

    def push(raw_segment: str, raw_start: int, raw_end: int) -> None:
        if not raw_segment.strip():
            return
        leading = len(raw_segment) - len(raw_segment.lstrip())
        trailing = len(raw_segment) - len(raw_segment.rstrip())
        start_offset = raw_start + leading
        end_offset = max(start_offset, raw_end - trailing)
        records.append(
            {
                "index": len(records) + 1,
                "text": raw_segment.strip(),
                "start_offset": start_offset,
                "end_offset": end_offset,
            }
        )

    for match in separator.finditer(content):
        push(content[last_index:match.start()], last_index, match.start())
        last_index = match.end()
    push(content[last_index:], last_index, len(content))
    return records


def _build_project_academic_export(
    sections: list[Any],
    drafts: list[Any],
    materials: list[Any],
) -> dict[str, list[dict[str, Any]]]:
    """Derive academic evidence view-models from existing materials and anchors."""
    material_lookup = {material.material_id: material for material in materials}
    anchors_by_material: dict[str, list[dict[str, Any]]] = {}
    citation_chain: list[dict[str, Any]] = []
    review_findings: list[dict[str, Any]] = []
    section_ids = {section.section_id for section in sections}

    for draft in drafts:
        draft_payload = draft.to_dict()
        anchors = draft_payload.get("citation_anchors", [])
        paragraphs = _paragraphs_with_offsets(str(getattr(draft, "content", "")))
        for anchor in anchors:
            if not isinstance(anchor, Mapping):
                continue
            material_id = anchor.get("materialId")
            anchor_id = str(anchor.get("id", "")).strip()
            if material_id:
                anchors_by_material.setdefault(str(material_id), []).append(anchor)
            paragraph = next(
                (
                    item
                    for item in paragraphs
                    if int(anchor.get("startOffset", -1)) >= item["start_offset"]
                    and int(anchor.get("endOffset", -1)) <= item["end_offset"]
                ),
                None,
            )
            material = material_lookup.get(str(material_id)) if material_id else None
            excerpt = _material_excerpt(material) if material else ""
            citation_chain.append(
                {
                    "anchor_id": anchor_id,
                    "section_id": draft.section_id if draft.section_id in section_ids else None,
                    "paragraph_index": paragraph["index"] if paragraph else None,
                    "material_id": material.material_id if material else material_id,
                    "evidence_id": f"evidence:{material.material_id}" if material else None,
                    "claim_excerpt": (
                        _shorten_export_text(_strip_citation_tokens(paragraph["text"]))
                        if paragraph
                        else ""
                    ),
                    "source_excerpt": _shorten_export_text(excerpt) if excerpt else "",
                    "page": None,
                    "confidence": None,
                }
            )

        uncited_long = [
            paragraph
            for paragraph in paragraphs
            if len(_strip_citation_tokens(paragraph["text"])) >= 80
            and not any(
                int(anchor.get("startOffset", -1)) >= paragraph["start_offset"]
                and int(anchor.get("endOffset", -1)) <= paragraph["end_offset"]
                for anchor in anchors
                if isinstance(anchor, Mapping)
            )
        ]
        if uncited_long:
            review_findings.append(
                {
                    "id": f"uncited-paragraphs:{draft.draft_id}",
                    "severity": "warning",
                    "message": f"{len(uncited_long)} long paragraph(s) have no citation anchors.",
                    "draft_id": draft.draft_id,
                    "section_id": draft.section_id,
                }
            )

    for material_id in sorted(anchors_by_material):
        if material_id not in material_lookup:
            review_findings.append(
                {
                    "id": f"dangling-material:{material_id}",
                    "severity": "warning",
                    "message": "Citation anchor points to a material that is not in this project export.",
                    "material_id": material_id,
                }
            )

    evidence_rows: list[dict[str, Any]] = []
    for material in materials:
        excerpt = _material_excerpt(material)
        anchor_ids = [
            str(anchor.get("id", ""))
            for anchor in anchors_by_material.get(material.material_id, [])
        ]
        status = "unused"
        if anchor_ids:
            status = "used" if excerpt else "weak"
        evidence_rows.append(
            {
                "evidence_id": f"evidence:{material.material_id}",
                "material_id": material.material_id,
                "chunk_id": None,
                "page": None,
                "excerpt": _shorten_export_text(excerpt),
                "score": None,
                "provenance": {
                    "material_title": material.title,
                    "material_type": material.type,
                },
                "anchor_ids": anchor_ids,
                "status": status,
            }
        )

    return {
        "evidence_rows": evidence_rows,
        "citation_chain": citation_chain,
        "review_findings": review_findings,
    }


def _markdown_table_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()
