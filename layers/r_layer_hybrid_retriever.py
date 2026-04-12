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
    
    def __init__(self, use_reranker: bool = True):
        self.base_retriever = ContextAwareRetriever()
        self.use_reranker = use_reranker
        self.api_key = os.getenv("ARK_API_KEY") or os.getenv("SILICONFLOW_API_KEY")

    async def search(self, raw_data: Dict[str, Any], query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """
        完整流程: 混合检索 → 重排
        """
        # Step 1: 混合粗排 (Top 50)
        candidates = await self.base_retriever.hybrid_search(raw_data, query, top_k=50)
        
        if not candidates:
            return []

        # Step 2: 重排
        if self.use_reranker and self.api_key:
            try:
                candidates = await self._rerank_with_api(query, candidates)
            except Exception as e:
                logger.warning(f"Reranker API failed, using fallback: {e}")
                candidates = self._rerank_local(query, candidates)
        
        return candidates[:top_k]

    async def _rerank_with_api(self, query: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """模拟调用 BGE-Reranker API"""
        # 实际实现应调用 SiliconFlow / ARK
        for it in candidates:
            it['rerank_score'] = it.get('hybrid_score', 0) * 1.2
        candidates.sort(key=lambda x: x.get('rerank_score', 0), reverse=True)
        return candidates

    def _rerank_local(self, query: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """本地回退精排"""
        return sorted(candidates, key=lambda x: x.get('hybrid_score', 0), reverse=True)

# 保持对旧接口的兼容，但内部由类驱动
_retriever_instance = HybridRetrieverWithRerank()

async def hybrid_search(raw_extract: dict[str, Any], query: str, top_k: int = 12, focus_keywords: list[str] = None) -> list[dict[str, Any]]:
    return await _retriever_instance.search(raw_data=raw_extract, query=query, top_k=top_k)
