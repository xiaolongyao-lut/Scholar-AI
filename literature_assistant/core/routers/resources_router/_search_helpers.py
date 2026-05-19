# -*- coding: utf-8 -*-
"""Pure search-scoring helpers extracted from resources_router."""

from __future__ import annotations

import re
from typing import Any


__all__ = [
    "_tokenize_search_text",
    "_normalize_chunk_dedup_key",
    "_select_diverse_top_chunks",
    "_score_chunks_for_query",
]


def _tokenize_search_text(text: str) -> set[str]:
    normalized = text.lower().strip()
    if not normalized:
        return set()
    latin_tokens = re.findall(r"[a-z0-9_]+", normalized)
    cjk_chars = [ch for ch in normalized if "一" <= ch <= "鿿"]
    cjk_bigrams = ["".join(cjk_chars[idx:idx + 2]) for idx in range(len(cjk_chars) - 1)]
    cjk_tokens = cjk_bigrams or cjk_chars
    return set(latin_tokens + cjk_tokens)


def _normalize_chunk_dedup_key(content: str) -> str:
    normalized = re.sub(r"\s+", " ", content).strip().lower()
    return normalized[:300]


def _select_diverse_top_chunks(
    scored_chunks: list[tuple[float, dict[str, Any]]],
    top_k: int,
    max_chunks_per_material: int = 5,
) -> list[tuple[float, dict[str, Any]]]:
    positive_chunks = [(score, chunk) for score, chunk in scored_chunks if score > 0]
    if not positive_chunks:
        return []
    grouped: dict[str, list[tuple[float, dict[str, Any]]]] = {}
    material_order: list[str] = []
    for score, chunk in positive_chunks:
        material_key = str(chunk.get("material_id") or "")
        if material_key not in grouped:
            grouped[material_key] = []
            material_order.append(material_key)
        grouped[material_key].append((score, chunk))
    selected: list[tuple[float, dict[str, Any]]] = []
    seen_content_keys: set[tuple[str, str]] = set()
    for rank in range(max_chunks_per_material):
        added_this_round = False
        for material_key in material_order:
            material_chunks = grouped.get(material_key, [])
            if rank >= len(material_chunks):
                continue
            score, chunk = material_chunks[rank]
            content_key = _normalize_chunk_dedup_key(str(chunk.get("content") or ""))
            dedupe_key = (material_key, content_key)
            if dedupe_key in seen_content_keys:
                continue
            selected.append((score, chunk))
            seen_content_keys.add(dedupe_key)
            added_this_round = True
            if len(selected) >= top_k:
                return selected
        if not added_this_round:
            break
    return selected


def _score_chunks_for_query(
    chunks: list[dict[str, Any]],
    query: str,
) -> list[tuple[float, dict[str, Any]]]:
    if not isinstance(chunks, list):
        raise TypeError("chunks must be a list of chunk dictionaries")
    query_text = str(query or "").lower().strip()
    if not query_text:
        return []
    query_tokens = _tokenize_search_text(query_text)
    scored: list[tuple[float, dict[str, Any]]] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        title = str(chunk.get("title", "")).lower()
        text = str(chunk.get("content", "")).lower()
        combined = f"{title}\n{text}".strip()
        chunk_tokens = _tokenize_search_text(combined)
        score = 0.0
        if query_text in combined:
            score += 12.0
        if query_text in title:
            score += 4.0
        matched_tokens = query_tokens & chunk_tokens
        score += len(matched_tokens) * 2.0
        if query_tokens:
            score += (len(matched_tokens) / len(query_tokens)) * 4.0
        for token in query_tokens:
            if len(token) > 1 and token in title:
                score += 1.5
        scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored
