from __future__ import annotations

import asyncio
import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

# 加载 .env（SILICONFLOW_API_KEY / RERANK_API_KEY / ARK_API_KEY 等）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        for line in _env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

try:
    from layers.r_layer_hybrid_retriever import hybrid_search as hybrid_search_async
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency
    hybrid_search_async = None

try:
    from graph_keyword_retriever import build_keyword_graph, graph_keyword_search
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency
    build_keyword_graph = None
    graph_keyword_search = None

try:
    from chunk_vector_store import ChunkVectorStore
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency
    ChunkVectorStore = None

try:
    from reranker_client import rerank_async
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency
    rerank_async = None

try:
    from query_expander import translate_query_async
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency
    translate_query_async = None

try:
    from contextual_chunker import batch_contextualize
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency
    batch_contextualize = None


# 默认参数采用“建议值”，不是硬编码策略。
# 后续只需改这里即可全局生效（run_eval 默认值与 CLI 默认值共用）。
DEFAULT_TOP_K = 10
DEFAULT_RECALL_TOP_N = 100
DEFAULT_RERANK_TOP_N = 40
DEFAULT_USE_RERANK = True
# 实测：query expansion 在 v2.0 (414 条中文语料) 上反向收益 -12%
# （0.3043 → 0.2657）。翻译后英文 query 喂 dense 路引入噪声，RRF 稀释
# BM25/Graph 的精准命中。保留代码路径但默认关闭，需 --expansion 显式开。
DEFAULT_USE_EXPANSION = False
DEFAULT_QUERIES_PATH = "eval_queries_v2.0.jsonl"
DEFAULT_QUERY_CONCURRENCY = 8
DEFAULT_RERANK_CONCURRENCY = 3
DEFAULT_STRICT_CACHE_GUARD = True


def _calculate_mrr(relevance_list: list[bool]) -> float:
    for idx, is_rel in enumerate(relevance_list):
        if is_rel:
            return 1.0 / (idx + 1)
    return 0.0


def _calculate_recall_at_k(relevance_list: list[bool], k: int) -> float:
    return 1.0 if any(relevance_list[:k]) else 0.0


def _extract_candidate_doc_ids(hit: dict[str, Any]) -> set[str]:
    candidates = {
        str(hit.get("material_id", "")).strip(),
        str(hit.get("doc_id", "")).strip(),
        str(hit.get("id", "")).strip(),
    }
    chunk_id = str(hit.get("chunk_id", "")).strip()
    if chunk_id and "_chunk_" in chunk_id:
        candidates.add(chunk_id.split("_chunk_")[0])
    return {x for x in candidates if x}


def aggregate_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {
            "aggregated_metrics": {
                "recall_at_1": 0.0,
                "recall_at_3": 0.0,
                "recall_at_5": 0.0,
                "recall_at_10": 0.0,
                "mrr": 0.0,
                "avg_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
                "rerank_api_avg_ms": 0.0,
                "rerank_api_p95_ms": 0.0,
                "rerank_queue_avg_ms": 0.0,
                "rerank_queue_p95_ms": 0.0,
            },
            "per_difficulty": {},
        }

    def _avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    def _p95(values: list[float]) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        return round(s[min(len(s) - 1, int(len(s) * 0.95))], 2)

    latencies = sorted(float(r.get("latency_ms", 0.0)) for r in results)
    p95_idx = min(len(latencies) - 1, int(len(latencies) * 0.95))

    api_ms_list = [float(r["rerank_api_ms"]) for r in results if r.get("rerank_api_ms") is not None]
    queue_ms_list = [float(r["rerank_queue_wait_ms"]) for r in results if r.get("rerank_queue_wait_ms") is not None]

    aggregated = {
        "recall_at_1": _avg([float(r.get("recall_at_1", 0.0)) for r in results]),
        "recall_at_3": _avg([float(r.get("recall_at_3", 0.0)) for r in results]),
        "recall_at_5": _avg([float(r.get("recall_at_5", 0.0)) for r in results]),
        "recall_at_10": _avg([float(r.get("recall_at_10", 0.0)) for r in results]),
        "mrr": _avg([float(r.get("mrr", 0.0)) for r in results]),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2),
        "p95_latency_ms": round(latencies[p95_idx], 2),
        "rerank_api_avg_ms": round(sum(api_ms_list) / len(api_ms_list), 2) if api_ms_list else 0.0,
        "rerank_api_p95_ms": _p95(api_ms_list),
        "rerank_queue_avg_ms": round(sum(queue_ms_list) / len(queue_ms_list), 2) if queue_ms_list else 0.0,
        "rerank_queue_p95_ms": _p95(queue_ms_list),
    }

    per_difficulty: dict[str, dict[str, Any]] = {}
    for diff in sorted({str(r.get("difficulty", "unknown")) for r in results}):
        subset = [r for r in results if str(r.get("difficulty", "unknown")) == diff]
        per_difficulty[diff] = {
            "count": len(subset),
            "recall_at_5": _avg([float(r.get("recall_at_5", 0.0)) for r in subset]),
            "mrr": _avg([float(r.get("mrr", 0.0)) for r in subset]),
        }

    payload: dict[str, Any] = {
        "aggregated_metrics": aggregated,
        "per_difficulty": per_difficulty,
    }

    # Wave 1: template/non_template 分桶(仅当 results 里出现 is_template 字段时输出)
    if any("is_template" in r for r in results):
        per_template_bucket: dict[str, dict[str, Any]] = {}
        for flag in (True, False):
            subset = [r for r in results if r.get("is_template") is flag]
            if not subset:
                continue
            key = "template" if flag else "non_template"
            per_template_bucket[key] = {
                "count": len(subset),
                "recall_at_5": _avg([float(r.get("recall_at_5", 0.0)) for r in subset]),
                "mrr": _avg([float(r.get("mrr", 0.0)) for r in subset]),
            }
        if per_template_bucket:
            payload["per_template_bucket"] = per_template_bucket

    return payload


def _load_queries(queries_path: Path) -> list[dict[str, Any]]:
    if not queries_path.exists():
        raise FileNotFoundError(f"Query file not found: {queries_path}")
    with queries_path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _load_retrieval_corpus() -> dict[str, Any]:
    """加载 chunk_store 目录下所有 JSON，支持多种格式：

    - list[dict]               → 直接展平
    - {"chunks": list[dict]}   → 取 chunks 字段
    - {material_id: list[dict]}→ 按 material 分组（resources_router 产出格式）
    """
    chunk_store_dir = Path("output") / "chunk_store"
    if not chunk_store_dir.exists():
        return {"chunks": []}

    chunks: list[dict[str, Any]] = []
    for fp in chunk_store_dir.glob("*.json"):
        try:
            with fp.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, list):
                chunks.extend([x for x in payload if isinstance(x, dict)])
            elif isinstance(payload, dict):
                # 格式 1: {"chunks": [...]}
                raw = payload.get("chunks")
                if isinstance(raw, list):
                    chunks.extend([x for x in raw if isinstance(x, dict)])
                else:
                    # 格式 2: {material_id: [chunk, ...], ...}
                    for _key, val in payload.items():
                        if isinstance(val, list):
                            chunks.extend([x for x in val if isinstance(x, dict)])
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return {"chunks": chunks}


async def _retrieve(
    query_text: str,
    corpus: dict[str, Any],
    top_k: int,
    *,
    keyword_graph: dict[str, Any] | None = None,
    vector_store: Any | None = None,
    query_vec: Any | None = None,
    use_rerank: bool = True,
    rerank_top_n: int = 20,
    rerank_semaphore: Any | None = None,
    rerank_timings: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    hybrid_hits: list[dict[str, Any]] = []
    graph_hits: list[dict[str, Any]] = []
    dense_hits: list[dict[str, Any]] = []

    if hybrid_search_async:
        try:
            hits = await hybrid_search_async(corpus, query_text, top_k=top_k)
            hybrid_hits = hits if isinstance(hits, list) else []
        except (RuntimeError, TypeError, ValueError):
            hybrid_hits = []

    if keyword_graph and graph_keyword_search:
        try:
            chunks = corpus.get("chunks", []) if isinstance(corpus.get("chunks"), list) else []
            graph_hits = graph_keyword_search(keyword_graph, chunks, query=query_text, top_k=top_k)
        except (RuntimeError, TypeError, ValueError):
            graph_hits = []

    if vector_store is not None:
        try:
            dense_hits = await _dense_retrieve_precomputed(vector_store, query_vec, top_k)
        except (RuntimeError, TypeError, ValueError):
            dense_hits = []

    merged_hits = _rrf_fuse([hybrid_hits, graph_hits, dense_hits], top_k=max(top_k, rerank_top_n))
    if use_rerank and rerank_async and merged_hits:
        try:
            return await rerank_async(
                query_text, merged_hits[:rerank_top_n], top_k=top_k,
                semaphore=rerank_semaphore, timings=rerank_timings,
            )
        except (RuntimeError, TypeError, ValueError):
            pass
    return merged_hits[:top_k]


async def _dense_retrieve_precomputed(
    vector_store: Any, query_vec: Any, top_k: int
) -> list[dict[str, Any]]:
    """Dense retrieval with a pre-computed query vector (no API call)."""
    if query_vec is None:
        return []
    return vector_store.cosine_search(query_vec, top_k=top_k)


async def _retrieve_with_expansion(
    query_text: str,
    corpus: dict[str, Any],
    top_k: int,
    *,
    keyword_graph: dict[str, Any] | None = None,
    vector_store: Any | None = None,
    query_vec: Any | None = None,
    use_rerank: bool = True,
    rerank_top_n: int = 20,
    rerank_semaphore: Any | None = None,
    use_expansion: bool = False,
    expansion_semaphore: Any | None = None,
    recall_top_n: int = 100,
    rerank_timings: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Phase 5.2: split-routing translated retrieval.

    Why split-routing: r_layer_hybrid_retriever 的 BM25 把中英文 token
    分开统计（en_tokens / cn_tokens），英文 query 匹不到中文 chunk；
    graph_keyword_retriever 同理只在 token-level 命中。因此翻译只能
    喂给 bge-m3 dense 这一路，BM25 + Graph 必须保留中文原 query，
    否则 3 路 RRF 退化成 1 路，指标反而下降。

    接线：
      - BM25 (hybrid) + Graph：原中文 query_text
      - Dense：英文 translated query + 对应重嵌的 query_vec
      - Rerank：原中文 query_text（Qwen3-Reranker-8B 支持跨语言）
    """

    merge_top = max(top_k, rerank_top_n, recall_top_n)

    # --- 1. 非扩展路径：走原来的单 query 三路 -----------------------
    if not use_expansion or translate_query_async is None:
        return await _retrieve(
            query_text,
            corpus,
            top_k=merge_top,
            keyword_graph=keyword_graph,
            vector_store=vector_store,
            query_vec=query_vec,
            use_rerank=use_rerank,
            rerank_top_n=rerank_top_n,
            rerank_semaphore=rerank_semaphore,
            rerank_timings=rerank_timings,
        )

    # --- 2. 翻译（失败则降级到原 query）------------------------------
    translated = ""
    try:
        translated = await translate_query_async(query_text, semaphore=expansion_semaphore)
    except (RuntimeError, TypeError, ValueError):
        translated = ""

    translated = (translated or "").strip()
    if not translated or translated == query_text:
        # 翻译无效 / 无 API key，整个路径回退
        return await _retrieve(
            query_text,
            corpus,
            top_k=merge_top,
            keyword_graph=keyword_graph,
            vector_store=vector_store,
            query_vec=query_vec,
            use_rerank=use_rerank,
            rerank_top_n=rerank_top_n,
            rerank_semaphore=rerank_semaphore,
            rerank_timings=rerank_timings,
        )

    # --- 3. 英文 query 重嵌（dense 路专用）---------------------------
    translated_vec = query_vec
    if vector_store is not None:
        try:
            translated_vec = await vector_store.embed_query(translated)
        except (RuntimeError, TypeError, ValueError):
            translated_vec = query_vec

    # --- 4. 并行：BM25+Graph 走中文原 query，Dense 走英文 -----------
    hybrid_hits: list[dict[str, Any]] = []
    graph_hits: list[dict[str, Any]] = []
    dense_hits: list[dict[str, Any]] = []

    hybrid_task = None
    if hybrid_search_async:
        hybrid_task = asyncio.create_task(
            hybrid_search_async(corpus, query_text, top_k=merge_top)
        )

    # Graph / Dense 是同步或轻量协程，顺序调用即可
    if keyword_graph and graph_keyword_search:
        try:
            chunks = corpus.get("chunks", []) if isinstance(corpus.get("chunks"), list) else []
            graph_hits = graph_keyword_search(
                keyword_graph, chunks, query=query_text, top_k=merge_top
            )
        except (RuntimeError, TypeError, ValueError):
            graph_hits = []

    if vector_store is not None and translated_vec is not None:
        try:
            dense_hits = await _dense_retrieve_precomputed(
                vector_store, translated_vec, merge_top
            )
        except (RuntimeError, TypeError, ValueError):
            dense_hits = []

    if hybrid_task is not None:
        try:
            hits = await hybrid_task
            hybrid_hits = hits if isinstance(hits, list) else []
        except (RuntimeError, TypeError, ValueError):
            hybrid_hits = []

    # --- 5. RRF 合并 + 中文 query rerank ------------------------------
    merged = _rrf_fuse([hybrid_hits, graph_hits, dense_hits], top_k=merge_top)

    if use_rerank and rerank_async and merged:
        try:
            return await rerank_async(
                query_text, merged[:rerank_top_n], top_k=top_k,
                semaphore=rerank_semaphore, timings=rerank_timings,
            )
        except (RuntimeError, TypeError, ValueError):
            pass

    return merged[:top_k]


def _rrf_fuse(rank_lists: list[list[dict[str, Any]]], top_k: int, rrf_k: int = 60) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion for multiple ranked lists."""
    score_map: dict[str, float] = {}
    item_map: dict[str, dict[str, Any]] = {}

    def _item_key(item: dict[str, Any]) -> str:
        chunk_id = str(item.get("chunk_id", "")).strip()
        if chunk_id:
            return f"chunk::{chunk_id}"
        material_id = str(item.get("material_id", "")).strip()
        text = str(item.get("content") or item.get("claim") or item.get("text") or "").strip()
        return f"mat::{material_id}::{hash(text)}"

    for rank_list in rank_lists:
        for rank, item in enumerate(rank_list):
            if not isinstance(item, dict):
                continue
            key = _item_key(item)
            score_map[key] = score_map.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)
            if key not in item_map:
                item_map[key] = dict(item)

    ranked = sorted(score_map.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    fused: list[dict[str, Any]] = []
    for key, score in ranked:
        item = dict(item_map[key])
        item["rrf_score"] = round(score, 6)
        fused.append(item)
    return fused


def run_eval(
    queries_path: str = DEFAULT_QUERIES_PATH,
    output_path: str = "BASELINE_METRICS.json",
    top_k: int = DEFAULT_TOP_K,
    recall_top_n: int = DEFAULT_RECALL_TOP_N,
    use_rerank: bool = DEFAULT_USE_RERANK,
    rerank_top_n: int = DEFAULT_RERANK_TOP_N,
    use_expansion: bool = DEFAULT_USE_EXPANSION,
    use_contextual: bool = False,
    query_concurrency: int = DEFAULT_QUERY_CONCURRENCY,
    strict_cache_guard: bool = DEFAULT_STRICT_CACHE_GUARD,
    template_flags_path: str | None = None,
) -> dict[str, Any]:
    # 当前默认策略（Phase 5.2 分路路由修复后）：
    # - use_expansion=True：BM25/Graph 走中文原 query，Dense 走英文翻译，
    #   Rerank 走中文原 query。在翻译无效或无 API key 时优雅降级。
    # - recall_top_n=100 / rerank_top_n=40：提升召回深度与重排候选量，
    #   Qwen3-Reranker-8B 足以处理 top-40 而不显著拖累延迟（并发 8）。
    #
    # 后续调参建议：
    # 1) 若召回仍不足（Recall@10 偏低），把 recall_top_n 进一步上调到 150/200。
    # 2) 若排序不足（MRR 偏低），再上调 rerank_top_n 到 60，或尝试 --contextual。
    # 3) top_k 是产品展示策略（5 更精简，10 候选更多），不应替代检索质量调参。
    queries = _load_queries(Path(queries_path))
    corpus = _load_retrieval_corpus()

    # Phase 6: optionally prepend document-level context to chunks
    if use_contextual and batch_contextualize:
        chunks = corpus.get("chunks", []) if isinstance(corpus.get("chunks"), list) else []
        if chunks:
            contextualized_chunks = batch_contextualize(chunks)
            corpus = {**corpus, "chunks": contextualized_chunks}

    # Pre-build keyword graph once (Phase 3 perf fix)
    keyword_graph: dict[str, Any] | None = None
    if build_keyword_graph:
        chunks = corpus.get("chunks", []) if isinstance(corpus.get("chunks"), list) else []
        if chunks:
            keyword_graph = build_keyword_graph(chunks)

    # Wave 1: load template flags sidecar, used to tag results with is_template
    template_flags_map: dict[str, bool] | None = None
    if template_flags_path:
        flag_path = Path(template_flags_path)
        if flag_path.exists():
            template_flags_map = {}
            with flag_path.open("r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    rec = json.loads(stripped)
                    qid = rec.get("query_id")
                    if qid:
                        template_flags_map[qid] = bool(rec.get("is_template", False))

    # Run async portion (build vector store + batch embed queries + retrieve) in one event loop
    results = asyncio.run(
        _run_eval_async(
            queries,
            corpus,
            keyword_graph,
            top_k,
            recall_top_n=recall_top_n,
            use_rerank=use_rerank,
            rerank_top_n=rerank_top_n,
            use_expansion=use_expansion,
            query_concurrency=query_concurrency,
            strict_cache_guard=strict_cache_guard,
            template_flags_map=template_flags_map,
        )
    )

    summary = aggregate_metrics(results)
    payload = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_queries": len(queries),
        **summary,
    }

    with Path(output_path).open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return payload


async def _run_eval_async(
    queries: list[dict[str, Any]],
    corpus: dict[str, Any],
    keyword_graph: dict[str, Any] | None,
    top_k: int,
    *,
    recall_top_n: int,
    use_rerank: bool,
    rerank_top_n: int,
    use_expansion: bool,
    query_concurrency: int = DEFAULT_QUERY_CONCURRENCY,
    strict_cache_guard: bool = DEFAULT_STRICT_CACHE_GUARD,
    template_flags_map: dict[str, bool] | None = None,
) -> list[dict[str, Any]]:
    """Async eval loop — single event-loop, batch query embedding."""

    # Pre-build vector store (Phase 2 dense retrieval)
    vector_store = None
    if ChunkVectorStore is not None:
        chunks = corpus.get("chunks", []) if isinstance(corpus.get("chunks"), list) else []
        if chunks:
            cache_path = Path("output") / "embedding_cache" / "corpus_embeddings.npy"
            vector_store = await ChunkVectorStore.build(
                chunks,
                cache_path=cache_path,
                strict_cache_guard=strict_cache_guard,
            )

    # Pre-embed all query texts in batch (avoids 414 individual API calls)
    query_texts = [str(q.get("query_text", "")) for q in queries]
    query_vecs: list[Any] = [None] * len(queries)
    if vector_store is not None and vector_store.has_embeddings:
        try:
            query_vecs = await vector_store.batch_embed_queries(query_texts)
        except (RuntimeError, TypeError, ValueError):
            pass

    rerank_semaphore = asyncio.Semaphore(
        int(os.getenv("SILICONFLOW_RERANK_CONCURRENCY", str(DEFAULT_RERANK_CONCURRENCY)))
    ) if use_rerank else None

    expansion_semaphore = asyncio.Semaphore(
        int(os.getenv("ARK_EXPANSION_CONCURRENCY", "2"))
    ) if use_expansion else None

    # 查询级 gather 闸：避免 414 个协程同时挤在 rerank_semaphore 门口，
    # 导致 latency_ms 被"排队等"污染。默认与 rerank 并发对齐。
    query_gate = asyncio.Semaphore(max(1, int(query_concurrency)))

    async def _eval_one(i: int, q: dict[str, Any]) -> dict[str, Any]:
        async with query_gate:
            query_text = query_texts[i]
            difficulty = str(q.get("difficulty_level", "unknown"))
            evidence = q.get("evidence_set", []) if isinstance(q.get("evidence_set", []), list) else []
            expected_doc_ids = {
                str(item.get("doc_id", "")).strip() for item in evidence if isinstance(item, dict)
            }
            expected_doc_ids = {x for x in expected_doc_ids if x}

            rerank_timings: dict[str, float] = {}
            t0 = time.perf_counter()
            hits = await _retrieve_with_expansion(
                query_text, corpus, top_k=top_k,
                keyword_graph=keyword_graph,
                vector_store=vector_store,
                query_vec=query_vecs[i],
                use_rerank=use_rerank,
                rerank_top_n=rerank_top_n,
                rerank_semaphore=rerank_semaphore,
                use_expansion=use_expansion,
                expansion_semaphore=expansion_semaphore,
                recall_top_n=recall_top_n,
                rerank_timings=rerank_timings,
            )
            latency_ms = (time.perf_counter() - t0) * 1000

            relevance_list: list[bool] = []
            for hit in hits:
                if not isinstance(hit, dict):
                    relevance_list.append(False)
                    continue
                candidate_ids = _extract_candidate_doc_ids(hit)
                relevance_list.append(bool(candidate_ids.intersection(expected_doc_ids)))

            return {
                "query_id": q.get("query_id"),
                "difficulty": difficulty,
                "latency_ms": latency_ms,
                "rerank_api_ms": rerank_timings.get("api_ms"),
                "rerank_queue_wait_ms": rerank_timings.get("queue_wait_ms"),
                "rerank_attempts": rerank_timings.get("attempts"),
                "recall_at_1": _calculate_recall_at_k(relevance_list, 1),
                "recall_at_3": _calculate_recall_at_k(relevance_list, 3),
                "recall_at_5": _calculate_recall_at_k(relevance_list, 5),
                "recall_at_10": _calculate_recall_at_k(relevance_list, 10),
                "mrr": _calculate_mrr(relevance_list),
                **(
                    {"is_template": bool(template_flags_map.get(q.get("query_id"), False))}
                    if template_flags_map is not None
                    else {}
                ),
            }

    results: list[dict[str, Any]] = list(
        await asyncio.gather(*[_eval_one(i, q) for i, q in enumerate(queries)])
    )
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run retrieval evaluation.")
    parser.add_argument("--queries", default=DEFAULT_QUERIES_PATH)
    parser.add_argument("--output", default="BASELINE_METRICS.json")
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help="返回结果数（偏产品展示策略：5 更精简，10 候选更多）。",
    )
    parser.add_argument(
        "--recall-top-n",
        type=int,
        default=DEFAULT_RECALL_TOP_N,
        help="首轮召回深度；召回不足时优先上调到 80/100。",
    )
    parser.add_argument(
        "--rerank-top-n",
        type=int,
        default=DEFAULT_RERANK_TOP_N,
        help="重排候选深度；MRR 不足时可上调到 30/40。",
    )
    parser.add_argument("--no-rerank", action="store_true")
    expansion_group = parser.add_mutually_exclusive_group()
    expansion_group.add_argument(
        "--expansion",
        dest="use_expansion",
        action="store_true",
        help="启用 query expansion（仅在评测确认有效时开启）。",
    )
    expansion_group.add_argument(
        "--no-expansion",
        dest="use_expansion",
        action="store_false",
        help="禁用 query expansion（默认）。",
    )
    parser.set_defaults(use_expansion=DEFAULT_USE_EXPANSION)
    parser.add_argument("--contextual", action="store_true")
    strict_guard_group = parser.add_mutually_exclusive_group()
    strict_guard_group.add_argument(
        "--strict-cache-guard",
        dest="strict_cache_guard",
        action="store_true",
        help="启用 embedding cache manifest/hash 硬校验（默认开启）。",
    )
    strict_guard_group.add_argument(
        "--no-strict-cache-guard",
        dest="strict_cache_guard",
        action="store_false",
        help="关闭 embedding cache 硬校验（不推荐，仅用于兼容旧缓存）。",
    )
    parser.set_defaults(strict_cache_guard=DEFAULT_STRICT_CACHE_GUARD)
    parser.add_argument(
        "--query-concurrency",
        type=int,
        default=DEFAULT_QUERY_CONCURRENCY,
        help="同时发起的 query 协程数；设为 1 时串行（对齐 Phase 4 原版）。",
    )
    parser.add_argument(
        "--template-flags",
        type=str,
        default=None,
        help="Wave 1: audit 工具产出的 template_flags.jsonl；载入后按 template/non_template 分桶输出指标。",
    )
    args = parser.parse_args()

    final_metrics = run_eval(
        queries_path=args.queries,
        output_path=args.output,
        top_k=args.top_k,
        recall_top_n=args.recall_top_n,
        use_rerank=not args.no_rerank,
        rerank_top_n=args.rerank_top_n,
        use_expansion=args.use_expansion,
        use_contextual=args.contextual,
        query_concurrency=args.query_concurrency,
        strict_cache_guard=args.strict_cache_guard,
        template_flags_path=args.template_flags,
    )
    agg = final_metrics.get("aggregated_metrics", {})
    print("Evaluation completed.")
    print(
        f"Recall@5={agg.get('recall_at_5', 0.0)} | "
        f"MRR={agg.get('mrr', 0.0)} | "
        f"P95={agg.get('p95_latency_ms', 0.0)}ms | "
        f"API-p95={agg.get('rerank_api_p95_ms', 0.0)}ms | "
        f"Queue-p95={agg.get('rerank_queue_p95_ms', 0.0)}ms"
    )
