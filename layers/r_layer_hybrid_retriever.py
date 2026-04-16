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

logger = logging.getLogger("RLayer_HybridRetriever")

def normalize_text(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').replace('\xa0', ' ')).strip()

def en_tokens(text: str) -> list[str]:
    # 基础分词逻辑 (简化版)
    return [t.lower() for t in re.findall(r"[A-Za-z]+", text or '')]

def cn_tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[\u4e00-\u9fff]{2,}", text or '')]

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

    def _score_overlap(self, text: str, query: str) -> float:
        """核心词重叠评分"""
        q_toks = set(en_tokens(query) + cn_tokens(query))
        d_toks = set(en_tokens(text) + cn_tokens(text))
        if not q_toks: return 0.0
        return len(q_toks.intersection(d_toks)) / len(q_toks)

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

        results = []
        for chunk in chunks:
            # 1. BM25 模拟分
            bm25_score = self._score_overlap(chunk.get('claim', ''), query)
            
            # 2. Context 评分
            context_score = 0.0
            if self.use_context and 'context_summary' in chunk:
                context_score = self._score_overlap(chunk['context_summary'], query)
            
            # 3. Vector 评分
            vector_score = bm25_score 
            
            combined_score = (
                bm25_score * weights.get("bm25", 0.3) +
                vector_score * weights.get("vector", 0.4) +
                context_score * weights.get("context", 0.3)
            )
            
            res_item = dict(chunk)
            res_item['hybrid_score'] = round(combined_score, 4)
            results.append(res_item)

        results.sort(key=lambda x: x['hybrid_score'], reverse=True)
        return results[:top_k]

class HybridRetrieverWithRerank:
    """
    P1 WBS 1.3.2: 检索 + 重排 完整流程
    """
    
    def __init__(self, use_reranker: bool = True, cache_manager=None):
        self.base_retriever = ContextAwareRetriever()
        self.use_reranker = use_reranker
        self.rerank_api_key = os.getenv("SILICONFLOW_RERANK_API_KEY") or os.getenv("SILICONFLOW_API_KEY")
        self.rerank_base_url = os.getenv("SILICONFLOW_RERANK_BASE_URL", "https://api.siliconflow.cn/v1/rerank")
        self.rerank_model = os.getenv("SILICONFLOW_RERANK_MODEL", "Qwen/Qwen3-Reranker-8B")
        self.cache_manager = cache_manager

    async def search(self, raw_data: Dict[str, Any], query: str, top_k: int = 10, focus_keywords: List[str] = None) -> List[Dict[str, Any]]:
        """
        完整流程: 混合检索 → 重排 (P4 增强版: 前置命中查询)
        """
        if self.cache_manager:
            cached = await self.cache_manager.fetch(query, focus=focus_keywords, domain="retrieval")
            if cached:
                logger.info(f"⚡ 检索层缓存命中，直接返回结果: {query[:15]}...")
                return cached[:top_k]
        # Step 1: 混合粗排 (Top 50)
        candidates = await self.base_retriever.hybrid_search(raw_data, query, top_k=50)
        
        if not candidates:
            return []

        # Step 2: 重排
        if self.use_reranker and self.rerank_api_key:
            try:
                candidates = await self._rerank_with_api(query, candidates)
            except Exception as e:
                logger.warning(f"Reranker API failed, using fallback: {e}")
                candidates = self._rerank_local(query, candidates)
        
        final_results = candidates[:top_k]
        
        if self.cache_manager and final_results:
            # 记录查询特征，并作为新条目加入缓存
            await self.cache_manager.commit(query=query, result=final_results, focus=focus_keywords, domain="retrieval", confidence=0.8) # 检索本身不代表结论强度，置信度设为安全值
            
        return final_results

    async def _rerank_with_api(self, query: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """调用 SiliconFlow rerank API 对候选结果进行精排。"""
        documents = [
            normalize_text(
                item.get("claim")
                or item.get("text")
                or item.get("source_text")
                or ""
            )
            for item in candidates
        ]
        documents = [doc for doc in documents if doc]
        if not documents:
            return self._rerank_local(query, candidates)

        headers = {
            "Authorization": f"Bearer {self.rerank_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.rerank_model,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
            "return_documents": False,
        }

        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(self.rerank_base_url, headers=headers, json=payload)

        if response.status_code != 200:
            raise RuntimeError(f"rerank http {response.status_code}: {response.text[:240]}")

        try:
            body = response.json()
        except Exception:
            body = {}
        result_items = body.get("results", []) if isinstance(body, dict) else []
        if not isinstance(result_items, list) or not result_items:
            raise RuntimeError("rerank response missing results")

        # Map by original index for stable reorder
        score_by_index: Dict[int, float] = {}
        for raw in result_items:
            if not isinstance(raw, dict):
                continue
            idx = raw.get("index")
            score = raw.get("relevance_score")
            if isinstance(idx, int) and isinstance(score, (int, float)):
                score_by_index[idx] = float(score)

        if not score_by_index:
            raise RuntimeError("rerank response has no valid index/score pairs")

        reranked: List[Dict[str, Any]] = []
        for idx, item in enumerate(candidates):
            updated = dict(item)
            updated["rerank_score"] = score_by_index.get(idx, float(item.get("hybrid_score", 0.0)))
            reranked.append(updated)

        reranked.sort(key=lambda x: x.get("rerank_score", 0.0), reverse=True)
        return reranked

    def _rerank_local(self, query: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """本地回退精排"""
        return sorted(candidates, key=lambda x: x.get('hybrid_score', 0), reverse=True)

_retriever_instance = HybridRetrieverWithRerank()

async def hybrid_search(raw_extract: dict[str, Any], query: str, top_k: int = 12, focus_keywords: list[str] = None) -> list[dict[str, Any]]:
    return await _retriever_instance.search(raw_data=raw_extract, query=query, top_k=top_k, focus_keywords=focus_keywords)
