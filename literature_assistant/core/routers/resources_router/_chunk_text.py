# -*- coding: utf-8 -*-
"""Pure text-chunking helpers extracted from resources_router."""

from __future__ import annotations

import re
from typing import Any

from chunk_models import EnrichedChunk


__all__ = [
    "_split_text_into_chunks",
    "_recursive_split",
    "_detect_chunk_type",
    "_extract_section_title_from_line",
    "structure_aware_chunk",
    "_chunk_document",
]


_DEFAULT_CHUNK_SIZE = 800
_DEFAULT_CHUNK_OVERLAP = 150


def _split_text_into_chunks(
    text: str,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = _DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    if not text or len(text) <= chunk_size:
        return [text] if text else []
    separators = ["\n\n", "\n", "。", ".", "！", "!", "？", "?", "；", ";", " "]
    return _recursive_split(text, separators, chunk_size, chunk_overlap)


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
    parts = text.split(best_sep)
    chunks = []
    current = ""
    for part in parts:
        test = current + best_sep + part if current else part
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


def _chunk_document(
    material_id: str,
    title: str,
    content: str,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = _DEFAULT_CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
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
