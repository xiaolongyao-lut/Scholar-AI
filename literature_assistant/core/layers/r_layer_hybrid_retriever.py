# layers/r_layer_hybrid_retriever.py

import math
import re
import asyncio
import os
import httpx
import logging
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple
from layers.adaptive_weight_manager import AdaptiveWeightManager
from reranker_client import rerank_async, resolve_rerank_config, warm_rerank_live_candidate
from runtime_env import (
    build_embedding_failover_pool,
    build_embedding_request_payload,
    extract_embedding_vectors,
    resolve_embedding_config,
    resolve_embedding_request_url,
)
from retrieval_provenance import attach_source_labels, merge_source_labels
from rerank_logic_cache import get_rerank_cache # 新增

logger = logging.getLogger("RLayer_HybridRetriever")

DEFAULT_RERANK_PRE_TOPN = 30
DEFAULT_RERANK_PRE_TOPN_HARD_CAP = 60
RUNTIME_RERANK_ENABLED_ENV = "RAG_RUNTIME_RERANK_ENABLED"

def normalize_text(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').replace('\xa0', ' ')).strip()


def _get_env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _get_env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    logger.warning("Invalid boolean env %s=%r; using default=%s", name, raw, default)
    return default


def _runtime_rerank_enabled() -> bool:
    return _get_env_bool(RUNTIME_RERANK_ENABLED_ENV, default=False)


def _rerank_pre_topn_hard_cap() -> int:
    return max(1, _get_env_int("RERANK_PRE_TOPN_HARD_CAP", DEFAULT_RERANK_PRE_TOPN_HARD_CAP))


def _rerank_pre_topn(requested_top_k: int) -> int:
    return min(
        max(1, requested_top_k, _get_env_int("RERANK_PRE_TOPN", DEFAULT_RERANK_PRE_TOPN)),
        _rerank_pre_topn_hard_cap(),
    )

def _cosine_sim(a: list, b: list) -> float:
    """Cosine similarity between two vectors (plain Python, no numpy required)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

def en_tokens(text: str) -> list[str]:
    # 基础分词逻辑 (简化版)
    return [t.lower() for t in re.findall(r"[A-Za-z]+", text or '')]

def cn_tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[\u4e00-\u9fff]{2,}", text or '')]


def _bm25_terms(text: str) -> list[str]:
    """Tokenize text for the legacy BM25-compatible ranking helper."""
    return en_tokens(text) + cn_tokens(text)


def bm25_rank(
    chunks: list[dict[str, Any]],
    goal: str,
    text_key: str = "text",
    k1: float = 1.5,
    b: float = 0.75,
) -> list[dict[str, Any]]:
    """Rank chunk dictionaries with a deterministic BM25-lite score.

    Args:
        chunks: Chunk dictionaries to rank. Non-dict entries are ignored.
        goal: Non-empty query/goal text.
        text_key: Field containing the main searchable text.
        k1: BM25 term-frequency saturation parameter; must be positive.
        b: BM25 document-length normalization parameter, inclusive [0, 1].

    Returns:
        Ranked chunk dictionaries with a `bm25_score` field added.
    """
    if not isinstance(chunks, list):
        raise TypeError("chunks must be a list of dictionaries")
    if not str(goal or "").strip():
        return [dict(chunk, bm25_score=0.0) for chunk in chunks if isinstance(chunk, dict)]
    if k1 <= 0:
        raise ValueError("k1 must be positive")
    if b < 0 or b > 1:
        raise ValueError("b must be in the range [0, 1]")

    query_terms = _bm25_terms(goal)
    if not query_terms:
        return [dict(chunk, bm25_score=0.0) for chunk in chunks if isinstance(chunk, dict)]

    docs: list[tuple[dict[str, Any], list[str]]] = []
    document_frequency: Counter[str] = Counter()
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        text = str(chunk.get(text_key) or chunk.get("content") or chunk.get("claim") or "")
        terms = _bm25_terms(text)
        docs.append((chunk, terms))
        document_frequency.update(set(terms))

    if not docs:
        return []

    avg_doc_len = sum(len(terms) for _, terms in docs) / len(docs)
    avg_doc_len = avg_doc_len or 1.0
    total_docs = len(docs)
    query_term_counts = Counter(query_terms)
    ranked: list[dict[str, Any]] = []

    for chunk, terms in docs:
        term_frequency = Counter(terms)
        doc_len = len(terms) or 1
        score = 0.0
        for term, query_count in query_term_counts.items():
            if query_count <= 0:
                continue
            freq = term_frequency.get(term, 0)
            if freq <= 0:
                continue
            df = document_frequency.get(term, 0)
            idf = math.log(1.0 + ((total_docs - df + 0.5) / (df + 0.5)))
            denominator = freq + k1 * (1.0 - b + b * (doc_len / avg_doc_len))
            score += float(query_count) * idf * ((freq * (k1 + 1.0)) / denominator)

        ranked_chunk = dict(chunk)
        ranked_chunk["bm25_score"] = round(score, 6)
        ranked.append(ranked_chunk)

    ranked.sort(key=lambda item: item["bm25_score"], reverse=True)
    return ranked


class ContextAwareRetriever:
    """
    P1 WBS 1.3: 融合 BM25 + Vector + Context 的混合检索器
    """
    
    def __init__(self, use_context: bool = True):
        self.use_context = use_context
        # 初始融合权重 (待 calibrator 优化)
        self.weights = {
            "bm25": 0.3,
            "vector": 0.4,
            "context": 0.3
        }
        self.weight_manager = AdaptiveWeightManager()
        self._embed_api_key, self._embed_base_url, self._embed_model = resolve_embedding_config(
            default_base_url="https://api.siliconflow.cn/v1",
            default_model="BAAI/bge-m3",
        )
        self._embedding_pool = build_embedding_failover_pool(
            default_base_url="https://api.siliconflow.cn/v1",
            default_model="BAAI/bge-m3",
        )

    def _score_overlap(self, text: str, query: str) -> float:
        """核心词重叠评分"""
        q_toks = set(en_tokens(query) + cn_tokens(query))
        d_toks = set(en_tokens(text) + cn_tokens(text))
        if not q_toks: return 0.0
        return len(q_toks.intersection(d_toks)) / len(q_toks)

    async def _embed_query_once(
        self,
        query: str,
        api_key: str,
        base_url: str,
        model: str,
    ) -> list[float]:
        """Embed one query with one credential; raises on failure."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    resolve_embedding_request_url(base_url, model),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=build_embedding_request_payload(
                        [query],
                        base_url=base_url,
                        model=model,
                    ),
                )
                if resp.status_code == 200:
                    vectors = extract_embedding_vectors(resp.json())
                    if vectors:
                        return vectors[0]
                raise RuntimeError(f"embedding http {resp.status_code}: {resp.text[:240]}")
        except Exception as e:
            raise RuntimeError(f"Query embedding failed: {e}") from e

    async def _embed_query(self, query: str) -> list[float] | None:
        """Embed query with provider-aware failover. Returns None on failure."""
        if not self._embed_api_key and self._embedding_pool is None:
            return None
        try:
            if self._embedding_pool is not None:
                async def _invoke(cred: Any) -> list[float]:
                    return await self._embed_query_once(
                        query,
                        cred.api_key,
                        cred.base_url,
                        cred.model,
                    )

                return await self._embedding_pool.try_call_async(
                    "embedding",
                    _invoke,
                    cooldown_on=lambda _exc: True,
                )

            return await self._embed_query_once(
                query,
                self._embed_api_key,
                self._embed_base_url,
                self._embed_model,
            )
        except Exception as e:
            logger.debug("Query embedding failed: %s", e)
            return None

    async def hybrid_search(self, raw_extract: Dict[str, Any], query: str, top_k: int = 50, focus_keywords: List[str] = None) -> List[Dict[str, Any]]:
        """
        混合检索：综合信号
        """
        # P0: 动态分配权重
        weights = self.weights
        if focus_keywords and self.weight_manager:
            weights = await self.weight_manager.get_optimal_weights(focus_keywords)

        chunks = raw_extract.get('claim_index', []) or raw_extract.get('chunks', [])
        if not chunks:
            return []

        # Pre-compute query embedding if any chunk has embeddings
        query_vec = None
        has_dense = any(chunk.get('embedding') for chunk in chunks)
        if has_dense:
            query_vec = await self._embed_query(query)

        results = []
        for chunk in chunks:
            # 1. BM25 模拟分 — 兼容 claim / content / text 字段
            chunk_text = chunk.get('claim') or chunk.get('content') or chunk.get('text') or ''
            bm25_score = self._score_overlap(chunk_text, query)
            
            # 2. Context 评分
            context_score = 0.0
            if self.use_context and 'context_summary' in chunk:
                context_score = self._score_overlap(chunk['context_summary'], query)
            
            # 3. Vector 评分 — 使用真实余弦相似度
            vector_score = 0.0
            chunk_emb = chunk.get('embedding')
            if query_vec is not None and chunk_emb is not None and len(chunk_emb) > 0:
                vector_score = _cosine_sim(query_vec, chunk_emb)
            else:
                vector_score = bm25_score  # fallback when no embeddings
            
            combined_score = (
                bm25_score * weights.get("bm25", 0.3) +
                vector_score * weights.get("vector", 0.4) +
                context_score * weights.get("context", 0.3)
            )
            
            labels = ["bm25"]
            if query_vec is not None and chunk_emb is not None and len(chunk_emb) > 0:
                labels.append("dense")
            else:
                labels.append("dense_fallback")
            if self.use_context and 'context_summary' in chunk:
                labels.append("context")

            res_item = attach_source_labels(
                dict(chunk),
                labels,
                source_hint="+".join(merge_source_labels(labels)),
            )
            res_item['hybrid_score'] = round(combined_score, 4)
            results.append(res_item)

        results.sort(key=lambda x: x['hybrid_score'], reverse=True)
        return results[:top_k]

class HybridRetrieverWithRerank:
    """
    P1 WBS 1.3.2: 检索 + 重排 完整流程
    """
    
    def __init__(self, use_reranker: Optional[bool] = None, cache_manager=None):
        self.base_retriever = ContextAwareRetriever()
        self.use_reranker = _runtime_rerank_enabled() if use_reranker is None else bool(use_reranker)
        self.rerank_api_key, self.rerank_base_url, self.rerank_model = resolve_rerank_config()
        self.cache_manager = cache_manager
        self.durable_cache = get_rerank_cache() # 加固层

    async def search(self, raw_data: Dict[str, Any], query: str, top_k: int = 10, focus_keywords: List[str] = None) -> List[Dict[str, Any]]:
        """
        完整流程: 混合检索 → 重排 → 相关性过滤 (借鉴 RAG-Anything)
        """
        if self.cache_manager:
            cached = await self.cache_manager.fetch(query, focus=focus_keywords, domain="retrieval")
            if cached:
                logger.info(f"⚡ 检索层缓存命中，直接返回结果: {query[:15]}...")
                return cached[:top_k]

        rerank_candidate_limit = _rerank_pre_topn(top_k)

        # Step 1: 混合粗排 (Top 50, while preserving enough headroom for rerank pre-top-n)
        candidates = await self.base_retriever.hybrid_search(raw_data, query, top_k=max(50, rerank_candidate_limit))

        if not candidates:
            return []

        rerank_candidates = candidates[: min(len(candidates), rerank_candidate_limit)]

        # Step 2: 重排
        if self.use_reranker and self.rerank_api_key:
            # --- 拦截逻辑：检查 Rerank 持久化快照 ---
            cached_rerank = self.durable_cache.lookup(query, rerank_candidates)
            if cached_rerank:
                candidates = cached_rerank
            else:
                try:
                    warmup = await warm_rerank_live_candidate()
                    if warmup and warmup.get("warmed"):
                        logger.info(
                            "Rerank live warm-up ready: source=%s model=%s",
                            warmup.get("candidate_source"),
                            warmup.get("candidate_model"),
                        )
                    candidates = await self._rerank_with_api(query, rerank_candidates)
                    # 写入快照备忘
                    self.durable_cache.update(query, rerank_candidates, candidates)
                except Exception as e:
                    logger.warning(f"Reranker API failed, using fallback: {e}")
                    candidates = self._rerank_local(query, rerank_candidates)

        # Step 3: 相关性��分过滤与自适应智能截断 (DoD §2.3)
        # 针对精排分值进行硬截断，剔除噪声
        filtered_results = [
            c for c in candidates
            if c.get("rerank_score", 0.0) >= 0.15 or c.get("hybrid_score", 0.0) > 0.8
        ]

        if not filtered_results and candidates:
            # 如果全部被过滤，保留前 3 个兜底
            filtered_results = candidates[:3]
            logger.info("⚠️ 所有检索结果均低于阈值，保留 Top 3 兜底")

        # --- 自适应智能截断 (Selective Pruning) ---
        if len(filtered_results) >= 5:
            top1_score = filtered_results[0].get("rerank_score", 0.0)
            top5_score = filtered_results[4].get("rerank_score", 0.0)
            score_gap = top1_score - top5_score

            # 阈值规范: Gap > 0.4 且前排分值足够高，认为后排是噪声
            if score_gap > 0.4 and top1_score > 0.7:
                logger.info(f"✨ 触发智能截断: score_gap={score_gap:.3f}, top1={top1_score:.3f}. 压缩检索窗口至极简模式。")
                filtered_results = filtered_results[:3]

        final_results = filtered_results[:top_k]

        if self.cache_manager and final_results:
            await self.cache_manager.commit(query=query, result=final_results, focus=focus_keywords, domain="retrieval", confidence=0.8)

        return final_results

    async def _rerank_with_api(self, query: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """通过共享 reranker client 对候选结果进行精排。"""
        documents = [
            normalize_text(
                item.get("claim")
                or item.get("text")
                or item.get("content")
                or item.get("source_text")
                or ""
            )
            for item in candidates
        ]
        if not any(documents):
            return self._rerank_local(query, candidates)
        return await rerank_async(query, candidates, top_k=len(candidates))

    def _rerank_local(self, query: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """本地回退精排"""
        return [
            attach_source_labels(item, ["rerank_fallback"])
            for item in sorted(candidates, key=lambda x: x.get('hybrid_score', 0), reverse=True)
        ]

_retriever_instance = HybridRetrieverWithRerank()

async def hybrid_search(raw_extract: dict[str, Any], query: str, top_k: int = 12, focus_keywords: list[str] = None) -> list[dict[str, Any]]:
    return await _retriever_instance.search(raw_data=raw_extract, query=query, top_k=top_k, focus_keywords=focus_keywords)
