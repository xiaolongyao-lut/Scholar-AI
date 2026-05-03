from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = REPO_ROOT / "literature_assistant" / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tolf_text_selector import select_tolf_context_chunks


_BRIDGE_TOKEN_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+", re.UNICODE)
_QUERY_BRIDGE_LEXICON: Mapping[str, tuple[str, ...]] = {
    "激光焊接": ("laser", "welding", "weld", "laser welding"),
    "激光": ("laser",),
    "焊接": ("welding", "weld", "welded", "welds"),
    "力学性能": ("mechanical", "mechanical properties", "tensile", "hardness", "strength", "ductility"),
    "机械性能": ("mechanical", "mechanical properties", "tensile", "hardness", "strength", "ductility"),
    "钛合金": ("titanium", "titanium alloy", "ti alloy", "ti-6al-4v", "ti6al4v"),
    "铝合金": ("aluminum", "aluminium", "aluminum alloy", "aluminium alloy", "al alloy"),
    "镁合金": ("magnesium", "magnesium alloy", "mg alloy"),
    "高熵合金": ("high entropy alloy", "hea"),
    "显微组织": ("microstructure", "microstructural", "grain", "grains", "phase"),
    "微观组织": ("microstructure", "microstructural", "grain", "grains", "phase"),
    "组织": ("microstructure", "microstructural", "grain", "phase"),
    "硬度": ("hardness", "hv", "microhardness"),
    "强度": ("strength", "tensile strength", "yield strength", "uts"),
    "拉伸": ("tensile", "elongation", "ductility"),
    "疲劳": ("fatigue",),
    "断裂": ("fracture", "fractographic"),
    "裂纹": ("crack", "cracks", "cracking"),
    "气孔": ("porosity", "pore", "pores", "void"),
    "孔隙": ("porosity", "pore", "pores", "void"),
    "熔池": ("melt pool", "molten pool", "pool"),
    "热输入": ("heat input", "energy input", "line energy"),
    "冷却速度": ("cooling rate", "solidification rate"),
    "残余应力": ("residual stress", "residual stresses"),
    "晶粒": ("grain", "grains", "grain size"),
    "相变": ("phase transformation", "phase transition"),
    "工艺参数": ("process parameters", "processing parameters", "laser power", "scan speed", "welding speed"),
    "研究进展": ("review", "progress", "recent", "research", "study"),
    "最新": ("recent", "latest", "current"),
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"JSONL file not found: {path}")

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise TypeError(f"JSONL row {line_number} must be an object")
            rows.append(payload)
    return rows


def _chunk_content(chunk: Mapping[str, Any]) -> str:
    return str(
        chunk.get("content")
        or chunk.get("raw_content")
        or chunk.get("text")
        or chunk.get("source_text")
        or ""
    ).strip()


def _chunk_key(chunk: Mapping[str, Any], index: int) -> str:
    chunk_id = str(chunk.get("chunk_id") or chunk.get("id") or "").strip()
    if chunk_id:
        return chunk_id
    material_id = str(chunk.get("material_id") or "").strip()
    return f"{material_id or 'chunk'}:{index}"


def _normalize_chunk_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        content = _chunk_content(row)
        if not content:
            continue
        chunk = dict(row)
        chunk_id = _chunk_key(chunk, index)
        chunk["chunk_id"] = chunk_id
        chunk.setdefault("id", chunk_id)
        chunk["content"] = content
        chunks.append(chunk)
    return chunks


def _query_text(row: Mapping[str, Any], index: int) -> tuple[str, str]:
    query_id = str(row.get("query_id") or row.get("id") or f"q_{index + 1:04d}").strip()
    query = str(row.get("query_text") or row.get("query") or "").strip()
    if not query:
        raise ValueError(f"query row {index + 1} has no query_text/query")
    return query_id, query


def _score_default_chunks(query: str, chunks: Sequence[Mapping[str, Any]], top_k: int) -> list[dict[str, Any]]:
    from routers.resources_router import _score_chunks_for_query, _select_diverse_top_chunks

    scored = _score_chunks_for_query([dict(chunk) for chunk in chunks], query)
    selected = _select_diverse_top_chunks(scored, top_k=top_k)
    return [
        {"score": round(float(score), 4), **dict(chunk)}
        for score, chunk in selected
        if float(score) > 0
    ]


def _ids(chunks: Sequence[Mapping[str, Any]]) -> list[str]:
    return [str(chunk.get("chunk_id") or chunk.get("id") or "").strip() for chunk in chunks]


def _truncate_text(value: str, *, max_chars: int) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_chars <= 0 or len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max_chars - 1].rstrip()}…"


def _hit_snapshot(
    hit: Mapping[str, Any],
    *,
    snippet_chars: int,
    bridge_matches: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    content = _chunk_content(hit)
    snapshot: dict[str, Any] = {
        "chunk_id": str(hit.get("chunk_id") or hit.get("id") or "").strip(),
        "material_id": str(hit.get("material_id") or "").strip(),
        "title": str(hit.get("title") or "").strip(),
        "section_title": str(hit.get("section_title") or hit.get("section") or "").strip(),
        "page": hit.get("page"),
        "score": hit.get("score"),
        "source_labels": list(hit.get("source_labels") or []),
        "query_overlap_tokens": list(hit.get("query_overlap_tokens") or []),
        "snippet": _truncate_text(content, max_chars=snippet_chars),
    }
    if bridge_matches is not None:
        snapshot["query_bridge_matches"] = [
            {
                "query_term": str(match.get("query_term") or ""),
                "matched_terms": list(match.get("matched_terms") or []),
            }
            for match in bridge_matches
            if isinstance(match, Mapping)
        ]
    return snapshot


def _has_query_overlap(hit: Mapping[str, Any]) -> bool:
    raw_tokens = hit.get("query_overlap_tokens")
    if not isinstance(raw_tokens, list):
        return False
    return any(isinstance(token, str) and token.strip() for token in raw_tokens)


def _bridge_tokens(value: str) -> set[str]:
    return {token.lower() for token in _BRIDGE_TOKEN_RE.findall(value)}


def _compact(value: str) -> str:
    return "".join(_BRIDGE_TOKEN_RE.findall(value.lower()))


def _contains_bridge_term(term: str, *, text: str, tokens: set[str], compact_text: str) -> bool:
    normalized = str(term or "").strip().lower()
    if not normalized:
        return False
    if " " in normalized:
        return normalized in text
    if normalized in tokens:
        return True
    compact_term = _compact(normalized)
    return bool(compact_term and compact_term in compact_text)


def _query_bridge_matches(query: str, content: str) -> list[dict[str, Any]]:
    """Return zero-cost query-time bridge matches for diagnostic reporting.

    The output is intentionally additive and does not alter retrieval ranking.
    It mirrors mature query-expansion practice where synonyms explain recall gaps
    without replacing the original control query.
    """
    normalized_query = str(query or "").strip().lower()
    normalized_content = str(content or "").strip().lower()
    if not normalized_query or not normalized_content:
        return []

    query_tokens = _bridge_tokens(normalized_query)
    content_tokens = _bridge_tokens(normalized_content)
    query_compact = _compact(normalized_query)
    content_compact = _compact(normalized_content)
    matches: list[dict[str, Any]] = []

    for query_term, bridge_terms in _QUERY_BRIDGE_LEXICON.items():
        query_term_normalized = query_term.lower()
        if not (
            query_term_normalized in normalized_query
            or query_term_normalized in query_tokens
            or _compact(query_term_normalized) in query_compact
        ):
            continue
        matched_terms = [
            term
            for term in bridge_terms
            if _contains_bridge_term(
                term,
                text=normalized_content,
                tokens=content_tokens,
                compact_text=content_compact,
            )
        ]
        if matched_terms:
            matches.append({"query_term": query_term, "matched_terms": matched_terms})

    return matches


def _expanded_query_bridge_terms(query: str) -> list[str]:
    """Return deterministic query-time bridge terms for control diagnostics.

    The terms are appended only inside this evaluation tool so raw default
    search remains available as the primary control path.
    """
    normalized_query = str(query or "").strip().lower()
    if not normalized_query:
        return []

    query_tokens = _bridge_tokens(normalized_query)
    query_compact = _compact(normalized_query)
    expanded: list[str] = []
    seen: set[str] = set()
    for query_term, bridge_terms in _QUERY_BRIDGE_LEXICON.items():
        query_term_normalized = query_term.lower()
        if not (
            query_term_normalized in normalized_query
            or query_term_normalized in query_tokens
            or _compact(query_term_normalized) in query_compact
        ):
            continue
        for bridge_term in bridge_terms:
            normalized_bridge = str(bridge_term or "").strip().lower()
            if normalized_bridge and normalized_bridge not in seen:
                seen.add(normalized_bridge)
                expanded.append(normalized_bridge)
    return expanded


def _build_bilingual_control_query(query: str) -> tuple[str, list[str]]:
    terms = _expanded_query_bridge_terms(query)
    normalized_query = str(query or "").strip()
    if not terms:
        return normalized_query, []
    return f"{normalized_query} {' '.join(terms)}".strip(), terms


def _has_bridge_overlap(matches: Sequence[Any]) -> bool:
    for match in matches:
        if not isinstance(match, Mapping):
            continue
        matched_terms = match.get("matched_terms")
        if isinstance(matched_terms, Sequence) and not isinstance(matched_terms, (str, bytes)):
            if any(isinstance(term, str) and term.strip() for term in matched_terms):
                return True
    return False


def compare_context_selectors(
    queries: Sequence[Mapping[str, Any]],
    chunks: Sequence[Mapping[str, Any]],
    *,
    top_k: int = 5,
    max_queries: int | None = None,
    embedding_dim: int = 64,
    max_candidates: int = 45,
    include_inspection: bool = False,
    inspection_snippet_chars: int = 360,
) -> dict[str, Any]:
    """Compare default project chunk search with text-only TOLF selection.

    Args:
        queries: Query rows containing ``query_text`` or ``query``.
        chunks: Chunk rows containing content/text and optional provenance.
        top_k: Positive number of chunks selected by each method.
        max_queries: Optional positive query cap.
        embedding_dim: Positive local hashing embedding dimension.
        max_candidates: Positive prefilter cap before TOLF.
        include_inspection: Include side-by-side hit snippets for manual review.
        inspection_snippet_chars: Positive max snippet length for inspection rows.

    Returns:
        JSON-serializable comparison report.

    Raises:
        ValueError: If numeric arguments are invalid or query rows are malformed.
        TypeError: If queries/chunks are not sequences.
    """
    if isinstance(queries, (str, bytes)) or not isinstance(queries, Sequence):
        raise TypeError("queries must be a sequence of mapping objects")
    if isinstance(chunks, (str, bytes)) or not isinstance(chunks, Sequence):
        raise TypeError("chunks must be a sequence of mapping objects")
    if not isinstance(top_k, int) or top_k <= 0:
        raise ValueError("top_k must be a positive integer")
    if max_queries is not None and (not isinstance(max_queries, int) or max_queries <= 0):
        raise ValueError("max_queries must be a positive integer when provided")
    if not isinstance(embedding_dim, int) or embedding_dim <= 0:
        raise ValueError("embedding_dim must be a positive integer")
    if not isinstance(max_candidates, int) or max_candidates <= 0:
        raise ValueError("max_candidates must be a positive integer")
    if not isinstance(include_inspection, bool):
        raise TypeError("include_inspection must be a boolean")
    if not isinstance(inspection_snippet_chars, int) or inspection_snippet_chars <= 0:
        raise ValueError("inspection_snippet_chars must be a positive integer")

    normalized_chunks = _normalize_chunk_rows(chunks)
    query_rows = list(queries[:max_queries] if max_queries is not None else queries)
    comparisons: list[dict[str, Any]] = []

    for index, row in enumerate(query_rows):
        if not isinstance(row, Mapping):
            continue
        query_id, query = _query_text(row, index)
        default_hits = _score_default_chunks(query, normalized_chunks, top_k)
        bilingual_control_query, bilingual_query_terms = _build_bilingual_control_query(query)
        bilingual_default_hits = (
            _score_default_chunks(bilingual_control_query, normalized_chunks, top_k)
            if bilingual_query_terms
            else default_hits
        )
        try:
            tolf_hits = select_tolf_context_chunks(
                query,
                default_hits or normalized_chunks,
                top_k=top_k,
                embedding_dim=embedding_dim,
                max_candidates=max_candidates,
            )
        except (RuntimeError, TypeError, ValueError):
            tolf_hits = []

        default_ids = _ids(default_hits)
        bilingual_default_ids = _ids(bilingual_default_hits)
        tolf_ids = _ids(tolf_hits)
        overlap = [chunk_id for chunk_id in default_ids if chunk_id in set(tolf_ids)]
        bilingual_control_overlap = [
            chunk_id for chunk_id in bilingual_default_ids if chunk_id in set(tolf_ids)
        ]
        tolf_query_bridge_matches = [
            _query_bridge_matches(query, _chunk_content(hit))
            for hit in tolf_hits
        ]
        tolf_hits_without_query_overlap = sum(1 for hit in tolf_hits if not _has_query_overlap(hit))
        tolf_hits_without_query_or_bridge_overlap = sum(
            1
            for hit, bridge_matches in zip(tolf_hits, tolf_query_bridge_matches, strict=False)
            if not _has_query_overlap(hit) and not _has_bridge_overlap(bridge_matches)
        )
        tolf_hits_with_query_bridge_overlap = sum(
            1
            for hit, bridge_matches in zip(tolf_hits, tolf_query_bridge_matches, strict=False)
            if not _has_query_overlap(hit) and _has_bridge_overlap(bridge_matches)
        )
        comparison: dict[str, Any] = {
            "query_id": query_id,
            "query_text": query,
            "default_empty": not default_ids,
            "bilingual_default_empty": not bilingual_default_ids,
            "tolf_empty": not tolf_ids,
            "bilingual_query_terms": bilingual_query_terms,
            "default_top_ids": default_ids,
            "bilingual_default_top_ids": bilingual_default_ids,
            "tolf_top_ids": tolf_ids,
            "overlap_ids": overlap,
            "bilingual_control_overlap_ids": bilingual_control_overlap,
            "only_default_ids": [chunk_id for chunk_id in default_ids if chunk_id not in set(tolf_ids)],
            "only_bilingual_default_ids": [
                chunk_id for chunk_id in bilingual_default_ids if chunk_id not in set(tolf_ids)
            ],
            "only_tolf_ids": [chunk_id for chunk_id in tolf_ids if chunk_id not in set(default_ids)],
            "overlap_at_top_k": round(len(overlap) / max(1, top_k), 4),
            "bilingual_control_overlap_at_top_k": round(
                len(bilingual_control_overlap) / max(1, top_k),
                4,
            ),
            "tolf_hits_without_query_overlap": tolf_hits_without_query_overlap,
            "tolf_hits_without_query_or_bridge_overlap": tolf_hits_without_query_or_bridge_overlap,
            "tolf_hits_with_query_bridge_overlap": tolf_hits_with_query_bridge_overlap,
            "tolf_source_labels": [
                list(hit.get("source_labels") or [])
                for hit in tolf_hits
            ],
            "tolf_query_overlap_tokens": [
                list(hit.get("query_overlap_tokens") or [])
                for hit in tolf_hits
            ],
            "tolf_query_bridge_matches": tolf_query_bridge_matches,
        }
        if include_inspection:
            comparison["inspection"] = {
                "raw_default_hits": [
                    _hit_snapshot(hit, snippet_chars=inspection_snippet_chars)
                    for hit in default_hits
                ],
                "bilingual_default_hits": [
                    _hit_snapshot(hit, snippet_chars=inspection_snippet_chars)
                    for hit in bilingual_default_hits
                ],
                "tolf_hits": [
                    _hit_snapshot(
                        hit,
                        snippet_chars=inspection_snippet_chars,
                        bridge_matches=bridge_matches,
                    )
                    for hit, bridge_matches in zip(tolf_hits, tolf_query_bridge_matches, strict=False)
                ],
            }
        comparisons.append(comparison)

    mean_overlap = (
        round(sum(float(item["overlap_at_top_k"]) for item in comparisons) / len(comparisons), 4)
        if comparisons
        else 0.0
    )
    return {
        "schema_version": "tolf-context-selector-comparison/v1",
        "input": {
            "query_count": len(comparisons),
            "chunk_count": len(normalized_chunks),
            "top_k": top_k,
            "embedding_backend": "local_hashing_text_only",
            "embedding_dim": embedding_dim,
            "external_api_calls": 0,
        },
        "summary": {
            "mean_overlap_at_top_k": mean_overlap,
            "queries_with_tolf_hits": sum(1 for item in comparisons if item["tolf_top_ids"]),
            "queries_with_empty_default": sum(1 for item in comparisons if item["default_empty"]),
            "queries_with_empty_bilingual_default": sum(
                1 for item in comparisons if item["bilingual_default_empty"]
            ),
            "queries_where_bilingual_default_recovers_empty_default": sum(
                1
                for item in comparisons
                if item["default_empty"] and not item["bilingual_default_empty"]
            ),
            "queries_with_empty_tolf": sum(1 for item in comparisons if item["tolf_empty"]),
            "mean_bilingual_control_overlap_at_top_k": (
                round(
                    sum(float(item["bilingual_control_overlap_at_top_k"]) for item in comparisons)
                    / len(comparisons),
                    4,
                )
                if comparisons
                else 0.0
            ),
            "queries_where_all_tolf_hits_lack_query_overlap": sum(
                1
                for item in comparisons
                if item["tolf_top_ids"]
                and item["tolf_hits_without_query_overlap"] == len(item["tolf_top_ids"])
            ),
            "queries_where_all_tolf_hits_lack_query_or_bridge_overlap": sum(
                1
                for item in comparisons
                if item["tolf_top_ids"]
                and item["tolf_hits_without_query_or_bridge_overlap"] == len(item["tolf_top_ids"])
            ),
            "tolf_hits_without_query_overlap": sum(
                int(item["tolf_hits_without_query_overlap"]) for item in comparisons
            ),
            "tolf_hits_without_query_or_bridge_overlap": sum(
                int(item["tolf_hits_without_query_or_bridge_overlap"]) for item in comparisons
            ),
            "tolf_hits_with_query_bridge_overlap": sum(
                int(item["tolf_hits_with_query_bridge_overlap"]) for item in comparisons
            ),
        },
        "comparisons": comparisons,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _markdown_escape(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return text.replace("|", "\\|")


def _format_markdown_hits(label: str, hits: Sequence[Mapping[str, Any]]) -> list[str]:
    lines = [f"### {label}", ""]
    if not hits:
        return [*lines, "_No hits._", ""]

    for rank, hit in enumerate(hits, start=1):
        chunk_id = _markdown_escape(hit.get("chunk_id"))
        title = _markdown_escape(hit.get("title"))
        score = _markdown_escape(hit.get("score"))
        source_labels = ", ".join(str(item) for item in hit.get("source_labels") or [])
        overlap = ", ".join(str(item) for item in hit.get("query_overlap_tokens") or [])
        lines.extend(
            [
                f"{rank}. `{chunk_id}` | score `{score or 'n/a'}` | {title or 'untitled'}",
                f"   - source_labels: `{_markdown_escape(source_labels) or 'n/a'}`",
                f"   - query_overlap_tokens: `{_markdown_escape(overlap) or 'n/a'}`",
            ]
        )
        bridge_matches = hit.get("query_bridge_matches")
        if isinstance(bridge_matches, Sequence) and not isinstance(bridge_matches, (str, bytes)):
            bridge_text = "; ".join(
                f"{match.get('query_term')} -> {', '.join(str(term) for term in match.get('matched_terms') or [])}"
                for match in bridge_matches
                if isinstance(match, Mapping)
            )
            if bridge_text:
                lines.append(f"   - query_bridge_matches: `{_markdown_escape(bridge_text)}`")
        snippet = _markdown_escape(hit.get("snippet"))
        if snippet:
            lines.append(f"   - snippet: {snippet}")
    lines.append("")
    return lines


def _build_review_markdown(report: Mapping[str, Any], *, max_queries: int | None = None) -> str:
    comparisons = report.get("comparisons")
    if not isinstance(comparisons, Sequence) or isinstance(comparisons, (str, bytes)):
        raise TypeError("report comparisons must be a sequence")
    if max_queries is not None and (not isinstance(max_queries, int) or max_queries <= 0):
        raise ValueError("max_queries must be a positive integer when provided")

    query_rows = list(comparisons[:max_queries] if max_queries is not None else comparisons)
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# TOLF Comparison Review Packet",
        "",
        "This packet is for manual or goldset-aligned inspection. It is not a release gate.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in sorted(summary):
        lines.append(f"| `{_markdown_escape(key)}` | `{_markdown_escape(summary[key])}` |")
    lines.extend(
        [
            "",
            "## Review Rubric",
            "",
            "- Mark each arm as `relevant`, `partial`, `offtopic`, or `unknown`.",
            "- Prefer evidence that directly supports the query, not merely topic-adjacent chunks.",
            "- Do not treat bilingual bridge terms or TOLF activation as relevance labels.",
            "- If all arms are weak, record the query as needing rewrite, translation, or corpus inspection.",
            "",
            "## Queries",
            "",
        ]
    )

    for item in query_rows:
        if not isinstance(item, Mapping):
            continue
        inspection = item.get("inspection")
        if not isinstance(inspection, Mapping):
            continue
        query_id = _markdown_escape(item.get("query_id"))
        query_text = _markdown_escape(item.get("query_text"))
        bilingual_terms = ", ".join(str(term) for term in item.get("bilingual_query_terms") or [])
        lines.extend(
            [
                f"## {query_id}: {query_text}",
                "",
                f"- raw_default_empty: `{bool(item.get('default_empty'))}`",
                f"- bilingual_default_empty: `{bool(item.get('bilingual_default_empty'))}`",
                f"- tolf_empty: `{bool(item.get('tolf_empty'))}`",
                f"- bilingual_query_terms: `{_markdown_escape(bilingual_terms) or 'n/a'}`",
                f"- raw_tolf_overlap_ids: `{_markdown_escape(', '.join(str(x) for x in item.get('overlap_ids') or [])) or 'n/a'}`",
                f"- bilingual_tolf_overlap_ids: `{_markdown_escape(', '.join(str(x) for x in item.get('bilingual_control_overlap_ids') or [])) or 'n/a'}`",
                "",
                "Manual judgment:",
                "",
                "| Arm | Judgment | Notes |",
                "| --- | --- | --- |",
                "| raw_default | unknown |  |",
                "| bilingual_default | unknown |  |",
                "| tolf | unknown |  |",
                "",
            ]
        )
        lines.extend(_format_markdown_hits("Raw Default Hits", list(inspection.get("raw_default_hits") or [])))
        lines.extend(_format_markdown_hits("Bilingual Default Hits", list(inspection.get("bilingual_default_hits") or [])))
        lines.extend(_format_markdown_hits("TOLF Hits", list(inspection.get("tolf_hits") or [])))

    return "\n".join(lines).rstrip() + "\n"


def _write_review_markdown(path: Path, report: Mapping[str, Any], *, max_queries: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_build_review_markdown(report, max_queries=max_queries), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare default project chunk search with text-only TOLF context selection.")
    parser.add_argument("--queries", required=True, help="JSONL file with query_id/query_text rows.")
    parser.add_argument("--chunks", required=True, help="JSONL file with project-like chunk rows.")
    parser.add_argument("--output", required=True, help="Output JSON report path.")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-queries", type=int, default=None)
    parser.add_argument("--embedding-dim", type=int, default=64)
    parser.add_argument("--max-candidates", type=int, default=45)
    parser.add_argument("--include-inspection", action="store_true", help="Include side-by-side hit snippets for manual review.")
    parser.add_argument("--inspection-snippet-chars", type=int, default=360)
    parser.add_argument("--review-markdown-output", default=None, help="Optional Markdown review packet path; requires inspection output.")
    parser.add_argument("--review-max-queries", type=int, default=None)
    args = parser.parse_args()

    if args.review_markdown_output and not args.include_inspection:
        parser.error("--review-markdown-output requires --include-inspection")

    report = compare_context_selectors(
        _load_jsonl(Path(args.queries)),
        _load_jsonl(Path(args.chunks)),
        top_k=args.top_k,
        max_queries=args.max_queries,
        embedding_dim=args.embedding_dim,
        max_candidates=args.max_candidates,
        include_inspection=args.include_inspection,
        inspection_snippet_chars=args.inspection_snippet_chars,
    )
    _write_json(Path(args.output), report)
    if args.review_markdown_output:
        _write_review_markdown(Path(args.review_markdown_output), report, max_queries=args.review_max_queries)
    print(json.dumps({"status": "ok", "output": args.output, "query_count": report["input"]["query_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
