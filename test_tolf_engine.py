# -*- coding: utf-8 -*-
"""
TOLF Engine 单元测试
"""

import math
import numpy as np
import pytest
from layers.tolf_engine import (
    TOLFConfig,
    TOLFEngine,
    MAQWeightEngine,
    SpreadingActivationEngine,
    EvidenceGate,
    FishResult,
)


# ============================================================
# 辅助函数
# ============================================================

def make_random_embeddings(n: int, dim: int = 64, seed: int = 42) -> np.ndarray:
    """生成归一化的随机嵌入"""
    rng = np.random.RandomState(seed)
    emb = rng.randn(n, dim).astype(np.float32)
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    return emb / np.maximum(norms, 1e-10)


def make_chunks(n: int, point_types=None) -> list:
    """生成测试用 chunks"""
    types = point_types or ["result", "method", "background", "mechanism", "discussion"]
    return [
        {
            "id": f"chunk_{i}",
            "content": f"This is test chunk {i} about laser welding parameters and microstructure. "
                       f"The hardness was 250 HV and the grain size was 15 μm.",
            "point_type": types[i % len(types)],
        }
        for i in range(n)
    ]


# ============================================================
# MAQ Weight Engine 测试
# ============================================================


class TestMAQWeightEngine:

    def test_compute_corpus_stats(self):
        """测试语料库统计量计算"""
        cfg = TOLFConfig()
        engine = MAQWeightEngine(cfg)
        emb = make_random_embeddings(50, dim=32)

        mu, S_inv = engine.compute_corpus_stats(emb)
        assert mu.shape == (32,)
        assert S_inv.shape == (32, 32)
        # 均值应该接近零 (随机正态)
        assert np.abs(mu).max() < 1.0

    def test_mahalanobis_distance(self):
        """测试 Mahalanobis 距离计算"""
        cfg = TOLFConfig()
        engine = MAQWeightEngine(cfg)
        emb = make_random_embeddings(50, dim=16)
        mu, S_inv = engine.compute_corpus_stats(emb)

        # 均值点到自己的距离应该为 0
        d = engine.mahalanobis_distance(mu, mu, S_inv)
        assert d == pytest.approx(0.0, abs=1e-6)

        # 随机点到均值的距离应该 > 0
        d2 = engine.mahalanobis_distance(emb[0], mu, S_inv)
        assert d2 > 0

    def test_compute_query_weights(self):
        """测试权重分配在 [K_min, K_max] 范围内"""
        cfg = TOLFConfig(k_min=3, k_max=10)
        engine = MAQWeightEngine(cfg)
        emb = make_random_embeddings(100, dim=32)
        mu, S_inv = engine.compute_corpus_stats(emb)

        queries = make_random_embeddings(4, dim=32, seed=99)
        weights = engine.compute_query_weights(queries, mu, S_inv)

        assert len(weights) == 4
        for w in weights:
            assert cfg.k_min <= w <= cfg.k_max

    def test_compute_query_weights_single(self):
        """单查询应返回 K_max"""
        cfg = TOLFConfig(k_min=3, k_max=10)
        engine = MAQWeightEngine(cfg)
        emb = make_random_embeddings(50, dim=16)
        mu, S_inv = engine.compute_corpus_stats(emb)

        queries = make_random_embeddings(1, dim=16, seed=7)
        weights = engine.compute_query_weights(queries, mu, S_inv)
        assert weights == [10]

    def test_select_weight_points(self):
        """测试权重点选择"""
        cfg = TOLFConfig()
        engine = MAQWeightEngine(cfg)
        queries = make_random_embeddings(4, dim=32, seed=10)
        corpus = make_random_embeddings(100, dim=32, seed=20)
        weights = [3, 5, 4, 3]

        vertices = engine.select_weight_points(queries, corpus, weights)
        # 顶点数 = m(queries) + sum(weights)
        expected = len(queries) + sum(weights)
        assert len(vertices) == expected

    def test_convex_hull_filter_fallback(self):
        """点太少时应回退"""
        cfg = TOLFConfig()
        engine = MAQWeightEngine(cfg)
        corpus = make_random_embeddings(5, dim=6)
        # 太少的顶点无法构建凸包 (需 > dim+1 = 7 个点)
        vertices = make_random_embeddings(3, dim=6, seed=5)
        inside = engine.convex_hull_filter(corpus, vertices)
        # 回退策略仍应选中一些
        assert inside.sum() > 0

    def test_run_full_pipeline(self):
        """测试 MAQ 完整流程"""
        cfg = TOLFConfig(umap_n_components=3, umap_n_neighbors=2)
        engine = MAQWeightEngine(cfg)

        queries = make_random_embeddings(4, dim=32, seed=10)
        corpus = make_random_embeddings(50, dim=32, seed=20)

        inside, weights, w_dict = engine.run(queries, corpus)

        assert len(inside) == 50
        assert inside.dtype == bool
        assert len(weights) == 4
        assert len(w_dict) == 4
        assert abs(sum(w_dict.values()) - 1.0) < 1e-6

    def test_run_small_corpus(self):
        """语料库太小时应全部选中"""
        cfg = TOLFConfig(umap_n_components=6)
        engine = MAQWeightEngine(cfg)
        queries = make_random_embeddings(4, dim=16, seed=1)
        corpus = make_random_embeddings(5, dim=16, seed=2)

        inside, weights, w_dict = engine.run(queries, corpus)
        assert inside.sum() == 5  # 全部选中


# ============================================================
# Spreading Activation Engine 测试
# ============================================================


class TestSpreadingActivationEngine:

    def test_build_literature_graph(self):
        """测试图构建"""
        cfg = TOLFConfig()
        engine = SpreadingActivationEngine(cfg)
        chunks = make_chunks(20)
        emb = make_random_embeddings(20, dim=32)

        G = engine.build_literature_graph(chunks, emb, similarity_threshold=0.0)
        assert G.number_of_nodes() == 20
        # 阈值为 0 时应有很多边
        assert G.number_of_edges() > 0

    def test_build_graph_high_threshold(self):
        """高阈值应产生稀疏图"""
        cfg = TOLFConfig()
        engine = SpreadingActivationEngine(cfg)
        chunks = make_chunks(10)
        emb = make_random_embeddings(10, dim=32)

        G = engine.build_literature_graph(chunks, emb, similarity_threshold=0.99)
        assert G.number_of_nodes() == 10
        assert G.number_of_edges() <= 5  # 极少边

    def test_diffusion_process_basic(self):
        """测试基本扩散"""
        cfg = TOLFConfig(activation_threshold=0.3, k_hop=2)
        engine = SpreadingActivationEngine(cfg)

        # 手动构建邻接表: A → B → C
        adj = {
            "A": [("B", 0.8)],
            "B": [("A", 0.8), ("C", 0.6)],
            "C": [("B", 0.6)],
        }

        scores = engine.diffusion_process(adj, seed_nodes=["A"])

        # A 是种子，得分 = 1.0
        assert scores["A"] == 1.0
        # B 从 A 获得: min(1, 0 + 0.8 * 1.0) = 0.8
        assert scores["B"] == pytest.approx(0.8, abs=0.01)
        # C 从 B 获得: min(1, 0 + 0.6 * 0.8) = 0.48
        assert scores["C"] == pytest.approx(0.48, abs=0.01)

    def test_diffusion_with_initial_scores(self):
        """测试带初始分数的扩散"""
        cfg = TOLFConfig(k_hop=1)
        engine = SpreadingActivationEngine(cfg)

        adj = {
            "X": [("Y", 0.5)],
            "Y": [("X", 0.5)],
        }

        scores = engine.diffusion_process(
            adj, seed_nodes=["X"], initial_scores={"X": 0.7}
        )
        assert scores["X"] == pytest.approx(0.7, abs=0.01)
        assert scores["Y"] == pytest.approx(0.35, abs=0.01)

    def test_diffusion_score_capped_at_one(self):
        """激活分不应超过 1.0"""
        cfg = TOLFConfig(k_hop=3)
        engine = SpreadingActivationEngine(cfg)

        # 多个高权重路径汇聚
        adj = {
            "S1": [("T", 0.9)],
            "S2": [("T", 0.9)],
            "T": [("S1", 0.9), ("S2", 0.9)],
        }

        scores = engine.diffusion_process(adj, seed_nodes=["S1", "S2"])
        assert scores["T"] <= 1.0


# ============================================================
# Evidence Gate 测试
# ============================================================


class TestEvidenceGate:

    def test_evidence_score_result(self):
        """result 类型应得高分"""
        cfg = TOLFConfig()
        gate = EvidenceGate(cfg)
        chunk = {
            "point_type": "result",
            "content": "In this study, the hardness was 280 HV and wear rate decreased by 35%.",
        }
        score = gate.compute_evidence_score(chunk)
        assert score >= 0.85

    def test_evidence_score_background(self):
        """background 类型应得低分"""
        cfg = TOLFConfig()
        gate = EvidenceGate(cfg)
        chunk = {
            "point_type": "background",
            "content": "Previous studies have shown that laser welding is widely used.",
        }
        score = gate.compute_evidence_score(chunk)
        assert score <= 0.50

    def test_evidence_score_meta(self):
        """meta 类型应得极低分"""
        cfg = TOLFConfig()
        gate = EvidenceGate(cfg)
        chunk = {
            "point_type": "meta",
            "content": "University of Technology, Department of Materials",
        }
        score = gate.compute_evidence_score(chunk)
        assert score <= 0.15

    def test_hedge_penalty(self):
        """推测用语应降低证据分"""
        cfg = TOLFConfig()
        gate = EvidenceGate(cfg)
        chunk_firm = {
            "point_type": "result",
            "content": "The hardness increased to 300 HV in this study.",
        }
        chunk_hedge = {
            "point_type": "result",
            "content": "This may suggest the hardness could potentially increase.",
        }
        s_firm = gate.compute_evidence_score(chunk_firm)
        s_hedge = gate.compute_evidence_score(chunk_hedge)
        assert s_firm > s_hedge

    def test_gate_double_threshold(self):
        """双阈值门控测试"""
        cfg = TOLFConfig(activation_threshold=0.5, evidence_threshold=0.3)
        gate = EvidenceGate(cfg)

        chunks = [
            {"id": "c1", "point_type": "result",
             "content": "In this study hardness was 280 HV."},
            {"id": "c2", "point_type": "meta",
             "content": "University address."},
            {"id": "c3", "point_type": "result",
             "content": "The wear rate decreased by 40%."},
        ]

        activation = {"c1": 0.8, "c2": 0.9, "c3": 0.3}  # c3 激活分太低

        results = gate.gate(activation, chunks)

        ids = {r.chunk_id for r in results}
        assert "c1" in ids      # 高激活 + 高证据
        assert "c2" not in ids   # 高激活但低证据 (meta)
        assert "c3" not in ids   # 低激活


# ============================================================
# TOLF Engine 集成测试
# ============================================================


class TestTOLFEngine:

    def test_generate_aspect_queries(self):
        """aspect query 生成"""
        engine = TOLFEngine()
        queries = engine.generate_aspect_queries("激光焊接工艺对微观组织的影响")

        assert len(queries) == 4
        assert "knowledge" in queries
        assert "structure" in queries
        assert "result" in queries
        assert "value" in queries
        for v in queries.values():
            assert "激光焊接" in v

    def test_compute_initial_activation(self):
        """初始激活值计算"""
        engine = TOLFEngine()
        chunk_emb = make_random_embeddings(10, dim=32)
        query_emb = make_random_embeddings(4, dim=32, seed=99)
        weights = {"knowledge": 0.2, "structure": 0.3, "result": 0.3, "value": 0.2}
        chunk_ids = [f"c{i}" for i in range(10)]

        scores = engine.compute_initial_activation(
            chunk_emb, query_emb, weights, chunk_ids
        )

        assert len(scores) == 10
        for s in scores.values():
            assert 0.0 <= s <= 1.0

    def test_find_seed_nodes(self):
        """种子节点选择"""
        engine = TOLFEngine()
        scores = {"a": 0.9, "b": 0.1, "c": 0.7, "d": 0.5, "e": 0.3}
        seeds = engine.find_seed_nodes(scores, top_k=3)

        assert len(seeds) == 3
        assert seeds[0] == "a"
        assert seeds[1] == "c"

    def test_run_full_pipeline(self):
        """完整 TOLF 流程测试"""
        cfg = TOLFConfig(
            umap_n_components=3,
            umap_n_neighbors=2,
            activation_threshold=0.1,  # 降低阈值以便测试
            evidence_threshold=0.1,
        )
        engine = TOLFEngine(cfg)

        chunks = make_chunks(30)
        emb = make_random_embeddings(30, dim=32)
        query_emb = make_random_embeddings(4, dim=32, seed=99)

        results = engine.run(
            goal="激光焊接工艺对微观组织的影响",
            chunks=chunks,
            embeddings=emb,
            aspect_query_embeddings=query_emb,
        )

        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, FishResult)
            assert r.activation_score > cfg.activation_threshold
            assert r.evidence_score > cfg.evidence_threshold
            assert len(r.aspect_weights) == 4

    def test_run_without_embeddings(self):
        """不提供 aspect embedding 时应优雅降级"""
        cfg = TOLFConfig(activation_threshold=0.1, evidence_threshold=0.1)
        engine = TOLFEngine(cfg)

        chunks = make_chunks(10)
        emb = make_random_embeddings(10, dim=32)

        results = engine.run(
            goal="测试目标",
            chunks=chunks,
            embeddings=emb,
            aspect_query_embeddings=None,
        )

        assert isinstance(results, list)

    def test_run_empty_chunks(self):
        """空输入应返回空列表"""
        engine = TOLFEngine()
        results = engine.run(
            goal="test",
            chunks=[],
            embeddings=np.array([]).reshape(0, 32),
        )
        assert results == []

    def test_convex_hull_reduces_noise(self):
        """凸包过滤应减少噪声"""
        cfg = TOLFConfig(
            umap_n_components=3,
            umap_n_neighbors=2,
            activation_threshold=0.01,
            evidence_threshold=0.01,
        )
        engine = TOLFEngine(cfg)

        # 构造有结构的数据: 前10个与query相关，后20个是噪声
        rng = np.random.RandomState(42)
        query_emb = rng.randn(4, 32).astype(np.float32)
        
        # 相关 chunks: 靠近 query embeddings
        related = query_emb[0:1] + rng.randn(10, 32) * 0.1
        # 噪声 chunks: 远离
        noise = rng.randn(20, 32) * 3.0 + 5.0

        all_emb = np.vstack([related, noise]).astype(np.float32)
        chunks = make_chunks(30)

        results = engine.run(
            goal="test filtering",
            chunks=chunks,
            embeddings=all_emb,
            aspect_query_embeddings=query_emb.astype(np.float32),
        )

        # 应该不是全部 30 个都通过
        assert len(results) < 30


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
