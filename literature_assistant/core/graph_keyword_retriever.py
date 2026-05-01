from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any

from retrieval_provenance import attach_source_labels
from text_utils import cjk_aware_tokenize


_CJK_TOKEN_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def _en_tokens(text: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z]{3,}", text or "")]


def _cn_tokens(text: str) -> list[str]:
    return [t for t in cjk_aware_tokenize(text or "") if _CJK_TOKEN_RE.search(t)]


_QUERY_EXPANSION: dict[str, list[str]] = {
    "激光焊接": ["laser", "welding", "keyhole"],
    "熔池": ["melt", "pool", "keyhole"],
    "微观组织": ["microstructure", "grain"],
    "力学性能": ["hardness", "strength", "fatigue"],
    "裂纹": ["crack", "defect", "porosity"],
    "钛合金": ["titanium", "ti-6al", "ti6al4v"],
    "铝合金": ["aluminum", "aluminium"],
    "热处理": ["heat", "treatment", "diffusion", "nitriding"],
    "耐磨": ["wear", "tribology"],
    "残余应力": ["residual", "stress"],
    "电弧焊": ["arc", "tig", "mig", "gmaw"],
    "深度学习": ["deep", "learning", "neural"],
}


def _extract_chunk_text(chunk: dict[str, Any]) -> str:
    return str(
        chunk.get("content")
        or chunk.get("claim")
        or chunk.get("text")
        or ""
    )


def _keywords_from_text(text: str) -> set[str]:
    return set(_en_tokens(text) + _cn_tokens(text))


def _expanded_query_keywords(query: str) -> set[str]:
    raw = set(_en_tokens(query) + _cn_tokens(query))
    expanded = set(raw)
    for cn_key, en_vals in _QUERY_EXPANSION.items():
        if cn_key in query or cn_key in raw:
            expanded.update(en_vals)
    return expanded


def build_keyword_graph(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """构建关键词-Chunk 二部图索引。"""
    keyword_to_chunk_ids: dict[str, set[int]] = defaultdict(set)
    chunk_keywords: list[set[str]] = []

    for idx, chunk in enumerate(chunks):
        text = _extract_chunk_text(chunk)
        kws = _keywords_from_text(text)
        chunk_keywords.append(kws)
        for kw in kws:
            keyword_to_chunk_ids[kw].add(idx)

    n_chunks = max(len(chunks), 1)
    idf: dict[str, float] = {}
    for kw, posting in keyword_to_chunk_ids.items():
        df = len(posting)
        idf[kw] = math.log((1 + n_chunks) / (1 + df)) + 1.0

    # set -> sorted list，便于序列化与稳定性
    posting_lists = {kw: sorted(ids) for kw, ids in keyword_to_chunk_ids.items()}

    return {
        "keyword_to_chunk_ids": posting_lists,
        "chunk_keywords": [sorted(x) for x in chunk_keywords],
        "idf": idf,
    }


def graph_keyword_search(
    graph: dict[str, Any],
    chunks: list[dict[str, Any]],
    query: str,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """基于关键词二部图检索相关 chunk。"""
    if not query.strip() or not chunks:
        return []

    posting_lists = graph.get("keyword_to_chunk_ids", {})
    idf = graph.get("idf", {})

    q_kws = _expanded_query_keywords(query)
    if not q_kws:
        return []

    scores: dict[int, float] = defaultdict(float)
    for kw in q_kws:
        chunk_ids = posting_lists.get(kw, [])
        if not chunk_ids:
            continue
        weight = float(idf.get(kw, 1.0))
        for cid in chunk_ids:
            scores[cid] += weight

    if not scores:
        return []

    ranked_ids = sorted(scores.keys(), key=lambda i: scores[i], reverse=True)[:top_k]

    out: list[dict[str, Any]] = []
    for cid in ranked_ids:
        item = attach_source_labels(dict(chunks[cid]), ["graph"], source_hint="graph")
        item["graph_score"] = round(scores[cid], 4)
        out.append(item)
    return out
