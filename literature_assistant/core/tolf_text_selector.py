"""Text-only TOLF context selector with cross-lingual bridge expansion."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from layers.tolf_engine import EvidenceGate, TOLFConfig, TOLFEngine
from retrieval_provenance import merge_source_labels

_TOKEN_RE = re.compile(r"[A-Za-z0-9_一-鿿]+", re.UNICODE)
_NUMERIC_EVIDENCE_RE = re.compile(
    r"\b\d+(?:\.\d+)?(?:\s*(?:%|wt\.%|um|μm|mm|nm|mpa|gpa|hv|°c|k|w|kw))\b",
    re.IGNORECASE,
)

_LEXICON_PATH = Path(__file__).resolve().parent / "config" / "cjk_bridge_lexicon.json"
_CJK_BRIDGE_LEXICON: dict[str, tuple[str, ...]] | None = None


def _load_bridge_lexicon() -> dict[str, tuple[str, ...]]:
    global _CJK_BRIDGE_LEXICON
    if _CJK_BRIDGE_LEXICON is not None:
        return _CJK_BRIDGE_LEXICON
    try:
        raw = json.loads(_LEXICON_PATH.read_text(encoding="utf-8"))
        _CJK_BRIDGE_LEXICON = {k: tuple(v) for k, v in raw.items()}
    except (OSError, json.JSONDecodeError, TypeError):
        _CJK_BRIDGE_LEXICON = {}
    return _CJK_BRIDGE_LEXICON


def _expand_query_with_bridge_terms(query: str) -> tuple[str, list[str]]:
    normalized = str(query or "").strip().lower()
    if not normalized:
        return query, []
    tokens = set(_TOKEN_RE.findall(normalized))
    lexicon = _load_bridge_lexicon()
    expanded: list[str] = []
    seen: set[str] = set()
    for cjk_term, bridge_terms in lexicon.items():
        if cjk_term.lower() not in normalized and cjk_term.lower() not in tokens:
            continue
        for bt in bridge_terms:
            bt_lower = bt.strip().lower()
            if bt_lower and bt_lower not in seen:
                seen.add(bt_lower)
                expanded.append(bt_lower)
    if not expanded:
        return query, []
    return f"{query} {' '.join(expanded)}".strip(), expanded


def _tokenize(value: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(value)]


def _token_bucket(token: str, dim: int) -> int:
    return int.from_bytes(hashlib.sha256(token.encode("utf-8")).digest()[:8], "big") % dim


def _make_hash_embeddings(texts: Sequence[str], *, dim: int = 256) -> np.ndarray:
    if not isinstance(dim, int) or dim <= 0:
        raise ValueError("dim must be a positive integer")
    matrix = np.zeros((len(texts), dim), dtype=np.float32)
    for row, text in enumerate(texts):
        for token in _tokenize(str(text or "")):
            matrix[row, _token_bucket(token, dim)] += 1.0
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    nonzero = norms[:, 0] > 0.0
    matrix[nonzero] = matrix[nonzero] / norms[nonzero]
    return matrix


def _try_api_embeddings(texts: Sequence[str], *, dim: int = 256) -> np.ndarray | None:
    """Attempt to use an env-configured embedding API; fall back to None."""
    base_url = os.getenv("TOLF_EMBEDDING_BASE_URL") or os.getenv("EMBEDDING_BASE_URL")
    api_key = os.getenv("TOLF_EMBEDDING_API_KEY") or os.getenv("EMBEDDING_API_KEY")
    model = os.getenv("TOLF_EMBEDDING_MODEL") or os.getenv("EMBEDDING_MODEL")
    if not (base_url and api_key and model):
        return None
    try:
        import httpx
        resp = httpx.post(
            f"{base_url.rstrip('/')}/embeddings",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": [str(t or "") for t in texts]},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        vecs = [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]
        arr = np.array(vecs, dtype=np.float32)
        if arr.shape[1] != dim:
            # Project via PCA-like random projection if dim mismatch
            rng = np.random.RandomState(42)
            proj = rng.randn(arr.shape[1], dim).astype(np.float32)
            proj /= np.linalg.norm(proj, axis=0, keepdims=True)
            arr = arr @ proj
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            nonzero = norms[:, 0] > 0.0
            arr[nonzero] = arr[nonzero] / norms[nonzero]
        return arr
    except Exception:
        return None


def make_local_text_embeddings(texts: Sequence[str], *, dim: int = 256) -> np.ndarray:
    """Create embeddings: API if configured, else local hash-based."""
    api_result = _try_api_embeddings(texts, dim=dim)
    if api_result is not None:
        return api_result
    return _make_hash_embeddings(texts, dim=dim)


def _chunk_content(chunk: Mapping[str, Any]) -> str:
    return str(
        chunk.get("content") or chunk.get("raw_content")
        or chunk.get("text") or chunk.get("source_text") or ""
    ).strip()


def _chunk_id(chunk: Mapping[str, Any], index: int) -> str:
    return str(chunk.get("chunk_id") or chunk.get("id") or f"chunk_{index}").strip()


_RESULT_HINTS = ("increased", "decreased", "improved", "result", "结果")
_METHOD_HINTS = ("method", "parameter", "process", "experiment", "工艺", "参数", "实验")
_MECHANISM_HINTS = ("mechanism", "cause", "because", "机理", "原因")
_BACKGROUND_HINTS = ("review", "background", "previous", "综述", "背景")


def _infer_point_type(content: str, raw: Any) -> str:
    existing = str(raw or "").strip().lower()
    if existing:
        return existing
    lower = content.lower()
    if _NUMERIC_EVIDENCE_RE.search(lower) or any(h in lower for h in _RESULT_HINTS):
        return "result"
    if any(h in lower for h in _METHOD_HINTS):
        return "method"
    if any(h in lower for h in _MECHANISM_HINTS):
        return "mechanism"
    if any(h in lower for h in _BACKGROUND_HINTS):
        return "background"
    return "discussion"


def _normalize_chunk(chunk: Mapping[str, Any], index: int) -> dict[str, Any] | None:
    content = _chunk_content(chunk)
    cid = _chunk_id(chunk, index)
    if not content or not cid:
        return None
    normalized = dict(chunk)
    normalized["id"] = cid
    normalized["chunk_id"] = cid
    normalized["content"] = content
    normalized["point_type"] = _infer_point_type(content, chunk.get("point_type"))
    normalized["_tolf_original_index"] = index
    return normalized


def _cosine_prefilter(
    query: str, chunks: list[dict[str, Any]], *, max_candidates: int, embedding_dim: int,
) -> list[dict[str, Any]]:
    if len(chunks) <= max_candidates:
        return chunks
    texts = [query, *(str(c["content"]) for c in chunks)]
    embs = make_local_text_embeddings(texts, dim=embedding_dim)
    scores = embs[1:] @ embs[0]
    top = np.argsort(-scores, kind="stable")[:max_candidates]
    return [chunks[int(i)] for i in top]


def _overlap_tokens(query: str, content: str) -> list[str]:
    return sorted(set(_tokenize(query)) & set(_tokenize(content)))


def _bridge_overlap_tokens(query: str, content: str) -> list[str]:
    qtoks = set(_tokenize(query))
    ctoks = set(_tokenize(content))
    direct = qtoks & ctoks
    if direct:
        return sorted(direct)
    english_in_query = {t for t in qtoks if re.match(r"^[a-z]", t)}
    return sorted(english_in_query & ctoks)


def _lexical_grounded_fallback(
    query: str,
    chunks: Sequence[Mapping[str, Any]],
    *,
    top_k: int,
    config: TOLFConfig,
    require_bridge_overlap: bool,
) -> list[dict[str, Any]]:
    """Return deterministic TOLF-labeled hits when graph activation is too sparse.

    Args:
        query: Expanded user query used by the main selector.
        chunks: Normalized candidate chunk dictionaries.
        top_k: Maximum number of hits to return.
        config: Evidence gate thresholds shared with the main TOLF path.
        require_bridge_overlap: Whether a lexical/bridge overlap is required.

    Returns:
        Ranked copies with the same provenance fields as normal TOLF hits.
    """
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return []

    gate = EvidenceGate(config)
    ranked: list[tuple[float, float, int, dict[str, Any], list[str], list[str]]] = []
    for index, chunk in enumerate(chunks):
        content = str(chunk.get("content") or "")
        query_overlap = _overlap_tokens(query, content)
        bridge_overlap = _bridge_overlap_tokens(query, content)
        if require_bridge_overlap and not query_overlap and not bridge_overlap:
            continue
        overlap_score = len(set(query_overlap) | set(bridge_overlap)) / max(1, len(query_tokens))
        if overlap_score <= 0.0:
            continue
        evidence_score = gate.compute_evidence_score(dict(chunk), query_tokens=query_tokens)
        ranked.append((overlap_score, evidence_score, -index, dict(chunk), query_overlap, bridge_overlap))

    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    selected: list[dict[str, Any]] = []
    for rank, (overlap_score, evidence_score, _order, chunk, query_overlap, bridge_overlap) in enumerate(
        ranked[:top_k],
        start=1,
    ):
        score = round(float(min(1.0, max(overlap_score, evidence_score * overlap_score))), 4)
        chunk["score"] = score
        chunk["tolf_activation_score"] = score
        chunk["tolf_evidence_score"] = round(float(evidence_score), 4)
        chunk["tolf_point_type"] = str(chunk.get("point_type") or "discussion")
        chunk["tolf_rank"] = rank
        chunk["query_overlap_tokens"] = query_overlap
        chunk["bridge_overlap_tokens"] = bridge_overlap
        chunk["source_labels"] = merge_source_labels(chunk.get("source_labels"), "tolf_text_selector")
        chunk["source_hint"] = "+".join(chunk["source_labels"])
        selected.append(chunk)
    return selected


def select_tolf_context_chunks(
    query: str,
    chunks: Sequence[Mapping[str, Any]],
    *,
    top_k: int,
    embedding_dim: int = 256,
    max_candidates: int = 45,
    activation_threshold: float = 0.6,
    evidence_threshold: float = 0.4,
    require_bridge_overlap: bool = True,
    boost_keywords: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Select project chunks through a zero-cost text-only TOLF evidence gate."""
    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise ValueError("query must be a non-empty string")
    if isinstance(chunks, (str, bytes)) or not isinstance(chunks, Sequence):
        raise TypeError("chunks must be a sequence of mapping objects")
    if not isinstance(top_k, int) or top_k <= 0:
        raise ValueError("top_k must be a positive integer")
    if not isinstance(embedding_dim, int) or embedding_dim <= 0:
        raise ValueError("embedding_dim must be a positive integer")
    if not isinstance(max_candidates, int) or max_candidates <= 0:
        raise ValueError("max_candidates must be a positive integer")

    normalized_chunks = [
        nc for i, c in enumerate(chunks)
        if isinstance(c, Mapping) and (nc := _normalize_chunk(c, i)) is not None
    ]
    if not normalized_chunks:
        return []

    expanded_query, _ = _expand_query_with_bridge_terms(normalized_query)

    # Inject research profile boost keywords into query expansion
    if boost_keywords:
        expanded_query += " " + " ".join(boost_keywords)

    candidate_cap = max(top_k, min(max_candidates, max(top_k, embedding_dim + 1)))
    candidates = _cosine_prefilter(
        expanded_query, normalized_chunks, max_candidates=candidate_cap, embedding_dim=embedding_dim,
    )
    if not candidates:
        return []

    aspect_queries = TOLFEngine().generate_aspect_queries(expanded_query)
    chunk_embs = make_local_text_embeddings(
        [str(c["content"]) for c in candidates], dim=embedding_dim,
    )
    aspect_embs = make_local_text_embeddings(list(aspect_queries.values()), dim=embedding_dim)

    config = TOLFConfig(
        activation_threshold=activation_threshold,
        evidence_threshold=evidence_threshold,
        umap_n_components=max(embedding_dim, len(candidates)),
        umap_n_neighbors=2,
        log_small_corpus_fallback=False,
    )
    fish_results = TOLFEngine(config).run(
        goal=expanded_query,
        chunks=[dict(c) for c in candidates],
        embeddings=chunk_embs,
        aspect_query_embeddings=aspect_embs,
    )

    by_chunk_id = {str(c["chunk_id"]): c for c in candidates}
    selected: list[dict[str, Any]] = []
    for rank, fish in enumerate(fish_results, start=1):
        source = by_chunk_id.get(str(fish.chunk_id))
        if source is None:
            continue
        updated = dict(source)
        updated["score"] = round(float(fish.activation_score), 4)
        updated["tolf_activation_score"] = round(float(fish.activation_score), 4)
        updated["tolf_evidence_score"] = round(float(fish.evidence_score), 4)
        updated["tolf_point_type"] = fish.point_type
        updated["tolf_rank"] = rank
        q_overlap = _overlap_tokens(expanded_query, str(updated.get("content") or ""))
        b_overlap = _bridge_overlap_tokens(expanded_query, str(updated.get("content") or ""))
        updated["query_overlap_tokens"] = q_overlap
        updated["bridge_overlap_tokens"] = b_overlap
        if require_bridge_overlap and not q_overlap and not b_overlap:
            continue
        updated["source_labels"] = merge_source_labels(updated.get("source_labels"), "tolf_text_selector")
        updated["source_hint"] = "+".join(updated["source_labels"])
        selected.append(updated)

    if not selected:
        selected = _lexical_grounded_fallback(
            expanded_query,
            candidates,
            top_k=top_k,
            config=config,
            require_bridge_overlap=require_bridge_overlap,
        )

    for new_rank, item in enumerate(selected[:top_k], start=1):
        item["tolf_rank"] = new_rank

    return selected[:top_k]
