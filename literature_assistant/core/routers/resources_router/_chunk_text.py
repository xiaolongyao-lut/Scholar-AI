# -*- coding: utf-8 -*-
"""Pure text-chunking helpers extracted from resources_router."""

from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

from chunk_models import EnrichedChunk
from chunk_size_guard import inspect_text

if TYPE_CHECKING:
    from pdf_backends import StructuredBlock


__all__ = [
    "_split_text_into_chunks",
    "_recursive_split",
    "_detect_chunk_type",
    "_extract_section_title_from_line",
    "structure_aware_chunk",
    "structure_aware_chunk_from_blocks",
    "_chunk_document",
]


_DEFAULT_CHUNK_SIZE = 800
_DEFAULT_CHUNK_OVERLAP = 150
_STRUCTURED_BLOCK_TYPE_MAPPING: dict[str, str] = {
    "Heading": "heading",
    "SectionHeader": "heading",
    "PageHeader": "heading",
    "Text": "narrative",
    "Paragraph": "narrative",
    "TextBlock": "narrative",
    "Footnote": "narrative",
    "PageFooter": "narrative",
    "Table": "table",
    "TableCaption": "table",
    "TableGroup": "table",
    "Equation": "formula",
    "Formula": "formula",
    "FigureCaption": "figure_caption",
    "Caption": "figure_caption",
    "FigureGroup": "figure_caption",
    "PictureGroup": "figure_caption",
    "List": "list",
    "ListItem": "list",
    "ListGroup": "list",
    "Code": "code",
    "CodeBlock": "code",
    "Image": "image_caption",
    "Figure": "image_caption",
    "Picture": "image_caption",
    "FullTextFallback": "fulltext_fallback",
}


def _map_structured_block_type(block_type: str | None) -> str:
    if not block_type:
        return "narrative"
    return _STRUCTURED_BLOCK_TYPE_MAPPING.get(block_type, "narrative")


_STRUCTURED_BREAK_MARKERS = ("\n\n", "\n", "。", "！", "？", ". ", "! ", "? ", "；", "; ", " ")

_VISUAL_STRUCTURED_BLOCK_TYPES = {
    "Equation",
    "Formula",
    "FigureCaption",
    "Caption",
    "FigureGroup",
    "PictureGroup",
    "Table",
    "TableCaption",
    "TableGroup",
    "Image",
    "Figure",
    "Picture",
}


def _structured_anchor_kind(block: "StructuredBlock", chunk_type: str) -> str:
    """Return the explicit anchor family for one structured source block."""

    if block.block_type in _VISUAL_STRUCTURED_BLOCK_TYPES or block.image_paths:
        return "visual"
    if chunk_type in {"formula", "table", "figure_caption", "image_caption"}:
        return "visual"
    return "text"


def _structured_segment_fits(content_prefix: str, segment: str) -> bool:
    """Return whether one exact source segment fits the persistence guard."""

    return not bool(inspect_text(f"{content_prefix}{segment}")["is_oversize"])


def _largest_fitting_structured_prefix(
    text: str,
    *,
    content_prefix: str,
    max_chars: int,
) -> int:
    """Return the longest leading character span that fits the hard guard."""

    upper = min(len(text), max_chars)
    if upper < 1:
        return 0
    if _structured_segment_fits(content_prefix, text[:upper]):
        return upper

    low = 1
    high = upper
    best = 0
    while low <= high:
        midpoint = (low + high) // 2
        if _structured_segment_fits(content_prefix, text[:midpoint]):
            best = midpoint
            low = midpoint + 1
        else:
            high = midpoint - 1
    return best


def _preferred_structured_boundary(text: str, hard_end: int) -> int:
    """Choose a nearby source boundary while retaining its separator bytes."""

    minimum_useful_end = max(1, hard_end // 2)
    best = 0
    for marker in _STRUCTURED_BREAK_MARKERS:
        marker_index = text.rfind(marker, 0, hard_end)
        if marker_index < 0:
            continue
        marker_end = marker_index + len(marker)
        if marker_end >= minimum_useful_end:
            best = max(best, marker_end)
    return best or hard_end


def _split_oversize_structured_text(text: str, *, content_prefix: str) -> list[str]:
    """Split structured text into exact, ordered hard-budget substrings.

    The returned segments concatenate byte-for-character to ``text``. Boundary
    punctuation and whitespace remain attached to one side of the split, so
    values such as ``1.0 mm`` cannot silently become ``10 mm``.
    """

    metrics = inspect_text(f"{content_prefix}{text}")
    if not bool(metrics["is_oversize"]):
        return [text]

    prefix_metrics = inspect_text(content_prefix)
    if bool(prefix_metrics["is_oversize"]):
        raise ValueError("structured chunk prefix exceeds the configured hard limit")
    available_chars = int(metrics["max_chars"]) - len(content_prefix)
    if available_chars < 1:
        raise ValueError("structured chunk prefix leaves no content character budget")

    output: list[str] = []
    offset = 0
    while offset < len(text):
        remaining = text[offset:]
        hard_end = _largest_fitting_structured_prefix(
            remaining,
            content_prefix=content_prefix,
            max_chars=available_chars,
        )
        if hard_end < 1:
            raise ValueError("structured chunk prefix leaves no content token budget")
        segment_end = _preferred_structured_boundary(remaining, hard_end)
        segment = remaining[:segment_end]
        if not _structured_segment_fits(content_prefix, segment):
            segment_end = hard_end
            segment = remaining[:segment_end]
        if not segment:
            raise ValueError("structured chunk splitter produced an empty segment")
        output.append(segment)
        offset += segment_end

    if "".join(output) != text:
        raise ValueError("structured chunk split did not preserve source text")
    if any(not _structured_segment_fits(content_prefix, part) for part in output):
        raise ValueError("structured chunk could not be split within the configured hard limit")
    return output


def _split_text_into_chunks(
    text: str,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = _DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    if not text or len(text) <= chunk_size:
        return [text] if text else []
    separators = ["\n\n", "\n", "。", ".", "！", "!", "？", "?", "；", ";", " "]
    return _recursive_split(text, separators, chunk_size, chunk_overlap)


def _split_preserving_separator(text: str, separator: str) -> list[str]:
    """Split text while retaining every separator character in source order."""

    if not separator:
        return [text]

    parts: list[str] = []
    start = 0
    while start < len(text):
        marker_index = text.find(separator, start)
        if marker_index < 0:
            parts.append(text[start:])
            break
        marker_end = marker_index + len(separator)
        parts.append(text[start:marker_end])
        start = marker_end
    return parts


def _recursive_split(
    text: str,
    separators: list[str],
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    best_sep = ""
    for sep in separators:
        if sep in text:
            best_sep = sep
            break
    if not best_sep:
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunks.append(text[start:end])
            start = end - chunk_overlap if end < len(text) else end
        return chunks
    parts = _split_preserving_separator(text, best_sep)
    chunks = []
    current = ""
    for part in parts:
        test = current + part
        if len(test) <= chunk_size:
            current = test
        else:
            if current:
                chunks.append(current)
            if len(part) > chunk_size:
                sub_chunks = _recursive_split(
                    part, separators[separators.index(best_sep) + 1:] if best_sep in separators else [],
                    chunk_size, chunk_overlap,
                )
                chunks.extend(sub_chunks)
                current = ""
            else:
                current = part
    if current:
        chunks.append(current)
    if chunk_overlap > 0 and len(chunks) > 1:
        overlapped: list[str] = [chunks[0]]
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            overlap_text = prev[-chunk_overlap:] if len(prev) > chunk_overlap else prev
            overlapped.append(overlap_text + chunks[i])
        chunks = overlapped
    return chunks


def _detect_chunk_type(block: str) -> str:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if not lines:
        return "narrative"
    table_like_lines = sum(1 for line in lines if "|" in line)
    if table_like_lines >= max(2, len(lines) // 2):
        return "table"
    list_like_lines = sum(1 for line in lines if re.match(r"^([\-\*•]|\d+[\.)])\s+", line))
    if list_like_lines >= max(1, len(lines) // 2):
        return "list"
    formula_like_lines = sum(1 for line in lines if re.search(r"[=+\-*/^]|\\\(|\\\)|∑|∫", line))
    if formula_like_lines >= max(1, len(lines) // 2):
        return "formula"
    return "narrative"


def _extract_section_title_from_line(line: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    markdown_match = re.match(r"^#+\s+(.+)$", stripped)
    if markdown_match:
        return markdown_match.group(1).strip()
    cjk_heading_match = re.match(r"^第[一二三四五六七八九十百千0-9]+[章节部分]\s*(.+)?$", stripped)
    if cjk_heading_match:
        suffix = (cjk_heading_match.group(1) or "").strip()
        return suffix or stripped
    return None


def structure_aware_chunk(
    text: str,
    material_id: str,
    title: str,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = _DEFAULT_CHUNK_OVERLAP,
) -> list[EnrichedChunk]:
    if not text.strip():
        return []
    chunks: list[EnrichedChunk] = []
    section_title = "正文"
    chunk_index = 0
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        maybe_heading = _extract_section_title_from_line(lines[0])
        content_lines = lines
        if maybe_heading:
            section_title = maybe_heading
            content_lines = lines[1:] if len(lines) > 1 else []
        block_content = "\n".join(content_lines).strip()
        if not block_content:
            continue
        chunk_type = _detect_chunk_type(block_content)
        raw_segments = [block_content]
        if chunk_type == "narrative":
            raw_segments = _split_text_into_chunks(block_content, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        for raw_segment in raw_segments:
            raw_text = str(raw_segment or "").strip()
            if not raw_text:
                continue
            prefixed_content = f"[文献: {title}][章节: {section_title}][类型: {chunk_type}]\n{raw_text}"
            chunks.append(
                EnrichedChunk(
                    chunk_id=f"{material_id}_chunk_{chunk_index}",
                    material_id=material_id,
                    title=title,
                    section_title=section_title,
                    chunk_index=chunk_index,
                    content=prefixed_content,
                    raw_content=raw_text,
                    chunk_type=chunk_type,
                    char_count=len(prefixed_content),
                )
            )
            chunk_index += 1
    return chunks


def structure_aware_chunk_from_blocks(
    blocks: list["StructuredBlock"],
    material_id: str,
    title: str,
) -> list[EnrichedChunk]:
    """Build EnrichedChunks directly from structured PDF blocks.

    Each source block normally becomes one EnrichedChunk because the upstream
    parser has already segmented by layout. Any textual block that exceeds the
    persistence hard limits is split without overlap before projection.
    Section_path is built by tracking a running stack of heading-block markdowns:
      - On Heading/SectionHeader/PageHeader: push to stack at appropriate
        level (we use a simple "replace the last element" strategy since
        external parsers may not emit heading-level depth reliably).
      - On any other block: section_path is the current stack snapshot.
    """
    if not blocks:
        return []

    enriched: list[EnrichedChunk] = []
    section_stack: list[str] = []
    current_section_title = "正文"
    chunk_index = 0
    HEADING_TYPES = {"Heading", "SectionHeader", "PageHeader"}

    for block in blocks:
        raw_md = (block.markdown or "").strip()
        if not raw_md:
            continue

        chunk_type = _map_structured_block_type(block.block_type)

        # Maintain section stack from heading blocks. We treat each heading
        # as overwriting the most recent entry — a deeper / richer heading-
        # level handling is out of scope (plan §1.5 mature reference =
        # LlamaIndex MarkdownNodeParser keeps the stack flat too).
        if block.block_type in HEADING_TYPES:
            heading_text = re.sub(r"^#+\s+", "", raw_md).strip() or raw_md
            if section_stack:
                section_stack[-1] = heading_text
            else:
                section_stack.append(heading_text)
            current_section_title = heading_text

        content_prefix = (
            f"[文献: {title}][章节: {current_section_title}][类型: {chunk_type}]\n"
        )
        raw_segments = _split_oversize_structured_text(raw_md, content_prefix=content_prefix)
        for raw_segment in raw_segments:
            prefixed_content = f"{content_prefix}{raw_segment}"
            enriched.append(
                EnrichedChunk(
                    chunk_id=f"{material_id}_chunk_{chunk_index}",
                    material_id=material_id,
                    title=title,
                    section_title=current_section_title,
                    chunk_index=chunk_index,
                    content=prefixed_content,
                    raw_content=raw_segment,
                    chunk_type=chunk_type,
                    char_count=len(prefixed_content),
                    page=int(block.page or 0),
                    bbox=list(block.bbox) if block.bbox else None,
                    bbox_unit=(str(block.bbox_unit).strip() if block.bbox and block.bbox_unit else None),
                    anchor_kind=_structured_anchor_kind(block, chunk_type),
                    section_path=list(section_stack) if section_stack else None,
                    image_paths=list(block.image_paths) if block.image_paths else None,
                    figure_id=block.figure_id,
                    table_id=block.table_id,
                    linked_figure_ids=list(block.linked_figure_ids) if block.linked_figure_ids else None,
                    linked_table_ids=list(block.linked_table_ids) if block.linked_table_ids else None,
                    table_csv=block.table_csv,
                    equation_latex=block.equation_latex,
                )
            )
            chunk_index += 1

    return enriched


def _chunk_document(
    material_id: str,
    title: str,
    content: str,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = _DEFAULT_CHUNK_OVERLAP,
    blocks: list["StructuredBlock"] | None = None,
) -> list[dict[str, Any]]:
    """Two-path chunker entry — see plan §1.5.

    Contract:
      - Default path (blocks is None / empty): output dict key set is
        **byte-level identical** to the previous implementation. New 5 fields
        DO NOT appear as keys.
      - structured path (blocks given): emits explicit locator identity plus
        section, image, figure/table relation, table, and equation fields.

    The key-set contract is locked by
    ``tests/test_chunk_document_default_path_dict_keys_unchanged.py``.
    """
    if blocks:
        # Structured parser path adds layout and provenance keys.
        enriched_chunks = structure_aware_chunk_from_blocks(
            blocks=blocks,
            material_id=material_id,
            title=title,
        )
        return [
            {
                "chunk_id": chunk.chunk_id,
                "material_id": chunk.material_id,
                "title": chunk.title,
                "section_title": chunk.section_title,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "raw_content": chunk.raw_content,
                "chunk_type": chunk.chunk_type,
                "char_count": chunk.char_count,
                "page": chunk.page,
                "embedding": chunk.embedding,
                "keywords": chunk.keywords,
                # Structured parser path ONLY.
                "bbox": chunk.bbox,
                "bbox_unit": chunk.bbox_unit,
                "anchor_kind": chunk.anchor_kind,
                "section_path": chunk.section_path,
                "image_paths": chunk.image_paths,
                "figure_id": chunk.figure_id,
                "table_id": chunk.table_id,
                "linked_figure_ids": chunk.linked_figure_ids,
                "linked_table_ids": chunk.linked_table_ids,
                "table_csv": chunk.table_csv,
                "equation_latex": chunk.equation_latex,
            }
            for chunk in enriched_chunks
        ]

    # Default PyMuPDF path — dict literal IDENTICAL to previous code path
    enriched_chunks = structure_aware_chunk(
        text=content,
        material_id=material_id,
        title=title,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return [
        {
            "chunk_id": chunk.chunk_id,
            "material_id": chunk.material_id,
            "title": chunk.title,
            "section_title": chunk.section_title,
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "raw_content": chunk.raw_content,
            "chunk_type": chunk.chunk_type,
            "char_count": chunk.char_count,
            "page": chunk.page,
            "embedding": chunk.embedding,
            "keywords": chunk.keywords,
        }
        for chunk in enriched_chunks
    ]
