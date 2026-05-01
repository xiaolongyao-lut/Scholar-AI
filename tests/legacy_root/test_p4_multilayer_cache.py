import asyncio
import json
import logging
from unittest.mock import MagicMock
from pathlib import Path

from layers.multi_layer_cache import MultiLayerCacheManager, QueryFingerprint
from layers.r_layer_hybrid_retriever import HybridRetrieverWithRerank
from layers.g_layer_academic_generator import AcademicScorer

logging.basicConfig(level=logging.DEBUG)

def test_multilayer_cache():
    # 1. 模拟 MemPalace L3
    mock_l3 = MagicMock()
    # 模拟第一次 search 返回空
    mock_l3_res = MagicMock()
    mock_l3_res.available = True
    mock_l3_res.results = []
    mock_l3.search.return_value = mock_l3_res

    manager = MultiLayerCacheManager(mempalace_adapter=mock_l3)

    import uuid
    domain_id = f"unit_test_{uuid.uuid4().hex}"
    
    # 2. 测试查询未命中
    async def run_cache():
        res = await manager.fetch("test query", domain=domain_id)
        assert res is None, "初始查询应该未命中"

        # 3. 提交新内容 (低置信度, 不应当触发 L3)
        await manager.commit("test query", {"foo": "bar"}, domain=domain_id, confidence=0.5)
        # 验证 L1 / L2
        key = QueryFingerprint.generate("test query", None, domain_id)
        assert manager.l1.get(key) == {"foo": "bar"}
        assert manager.l2.get(key) == {"foo": "bar"}
        mock_l3.add_memory.assert_not_called()

        # 4. 获取缓存应该命中
        hit = await manager.fetch("test query", domain=domain_id)
        assert hit == {"foo": "bar"}
        assert manager.stats["hits"] >= 1

        # 5. 提交高置信度 (应触发 L3)
        await manager.commit("high value query", {"insight": "deep"}, domain=domain_id, confidence=0.9)
        mock_l3.add_memory.assert_called_once()
        print("[SUCCESS] MultiLayerCacheManager 校验通过")

    asyncio.run(run_cache())

def test_retriever_caching():
    mock_manager = MagicMock()
    async def mock_fetch(query=None, focus=None, domain=None, **kwargs):
        q = query or kwargs.get("q", "")
        if "cached" in q:
            return [{"id": 1, "cached": True}]
        return None
    mock_manager.fetch.side_effect = mock_fetch

    async def mock_commit(*args, **kwargs):
        pass
    mock_manager.commit.side_effect = mock_commit

    retriever = HybridRetrieverWithRerank(use_reranker=False, cache_manager=mock_manager)

    async def run_retriever():
        # Hit Cache
        res1 = await retriever.search(raw_data={"chunks": [{"claim": "bar"}]}, query="cached_query", top_k=5)
        assert res1[0]["cached"] is True
        
        # Miss Cache
        res2 = await retriever.search(raw_data={"chunks": [{"claim": "bar"}]}, query="fresh_query", top_k=5)
        # 本地 rerank 的结果
        assert len(res2) > 0
        assert "cached" not in res2[0]
        # commit 应该被调用
        mock_manager.commit.assert_called()
        print("[SUCCESS] Retriever 缓存拦截校验通过")

    asyncio.run(run_retriever())

def test_academic_scorer_caching():
    mock_manager = MagicMock()
    async def mock_fetch(query=None, domain=None, **kwargs):
        q = query or kwargs.get("q", "")
        if "hit" in q:
            return {"goal": "cached", "status": "analysis_complete"}
        return None
    mock_manager.fetch.side_effect = mock_fetch

    async def mock_commit(*args, **kwargs):
        pass
    mock_manager.commit.side_effect = mock_commit

    scorer = AcademicScorer(goal="hit test_goal", enable_llm=False, cache_manager=mock_manager)
    
    async def run_scorer():
        res = await scorer.analyze_bound_data({"chunks": [], "figures": []})
        assert res.get("goal") == "cached"
        mock_manager.commit.assert_not_called()  # 因为命中缓存
        
        # Miss
        scorer.goal = "miss_goal"
        res_miss = await scorer.analyze_bound_data({"chunks": [], "figures": []})
        assert res_miss.get("goal") == "miss_goal"
        mock_manager.commit.assert_called()
        print("[SUCCESS] AcademicScorer 缓存拦截校验通过")

    asyncio.run(run_scorer())

if __name__ == "__main__":
    test_multilayer_cache()
    test_retriever_caching()
    test_academic_scorer_caching()
    print("ALL TESTS PASSED")
