# -*- coding: utf-8 -*-
"""
TOLF Engine — Target-Oriented Literature Fishing
=================================================

实现 TOLF 框架的三个核心量化组件：

1. **MAQ 权重** (MAQ-Retrieval, Xu et al. IEEE TAI 2026):
   Mahalanobis 距离自动定权 α,β,γ,δ → UMAP 降维 → Convex Hull 联合过滤

2. **扩散传播** (SA-RAG, Pavlović et al. 2025):
   NetworkX 图上的 BFS spreading activation，将约束掩码 m_q 融入边权

3. **证据门控**:
   独立实现 point_type 基础分 + 数值证据/当前工作/hedging 信号的轻量评分，
   与 scoring_engine.score_evidence 互补（后者侧重图表/引用计数）

公式对应：
    a_0(u) = α·f_K(u) + β·f_S(u) + γ·f_R(u) + δ·f_V(u)
    a^(t+1)(v) = λ·Σ[a_t(u)·w(u,v)·m_q(u,v)]
    u ∈ Fish ⟺ a(u) > τ_a AND e(u) > τ_e
"""

from __future__ import annotations

import logging
import math
import re
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Tuple

import networkx as nx
import numpy as np
from scipy import spatial as scipy_spatial

ConvexHull = getattr(scipy_spatial, "ConvexHull")
QhullError = getattr(scipy_spatial, "QhullError")

@lru_cache(maxsize=1)
def _check_umap_available() -> bool:
    """懒检查 umap 是否可用，避免模块级 import 拖慢启动速度。"""
    try:
        import importlib.util
        return importlib.util.find_spec('umap') is not None
    except (ImportError, AttributeError, ValueError):
        return False

logger = logging.getLogger(__name__)

RepresentativeReranker = Callable[[str, List["FishResult"]], List["FishResult"]]

# Token extraction pattern for lexical grounding
_TOKEN_RE = re.compile(r"[A-Za-z0-9_一-鿿]+", re.UNICODE)


# ============================================================
# 数据结构
# ============================================================


@dataclass
class TOLFConfig:
    """TOLF 引擎配置参数"""

    # --- MAQ-Retrieval 参数 (论文 Algorithm 1) ---
    k_min: int = 3                   # 最少选邻居点数
    k_max: int = 10                  # 最多选邻居点数
    umap_n_components: int = 6       # UMAP 降维目标维度 (论文推荐 6)
    umap_n_neighbors: int = 2        # UMAP 近邻数 (论文推荐 2)
    umap_min_dist: float = 1.0       # UMAP 最小距离 (论文推荐 1)
    umap_metric: str = "euclidean"   # UMAP 距离度量

    # --- SA-RAG 扩散参数 ---
    normalization_param: float = 0.4  # 边权归一化下限 c (论文 0.4)
    activation_threshold: float = 0.5 # 实体激活阈值 τ_a (论文 0.5)
    pruning_threshold: float = 0.45   # 边剪枝阈值 (论文 0.45)
    k_hop: int = 3                    # 最大传播跳数

    # --- 证据门控 ---
    evidence_threshold: float = 0.25  # 证据质量阈值 τ_e

    # --- 四层 aspect 名称 ---
    aspect_names: list = field(
        default_factory=lambda: ["knowledge", "structure", "result", "value"]
    )
    log_small_corpus_fallback: bool = True


@dataclass
class FishResult:
    """单个被捕获文献单元的结果"""
    chunk_id: str
    activation_score: float  # a(u)
    evidence_score: float    # e(u)
    aspect_weights: Dict[str, float]  # {K: α, S: β, R: γ, V: δ}
    point_type: str          # 来自 scoring_engine 的分类
    in_convex_hull: bool     # MAQ 凸包过滤结果
    content: str = ""


# ============================================================
# 组件 1: MAQ-Retrieval 权重引擎
# ============================================================


class MAQWeightEngine:
    """
    MAQ-Retrieval (Xu et al. IEEE TAI 2026) 的核心实现。

    三步流程：
    1. Mahalanobis 距离 → 自动权重 k_qi
    2. UMAP 降维（高维→6维）
    3. Convex Hull 构建 + 点内判定过滤
    """

    def __init__(self, config: TOLFConfig):
        self.config = config

    def compute_corpus_stats(
        self, embeddings: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        计算语料库的均值向量 μ 和协方差矩阵 S。

        Args:
            embeddings: shape (n, D) 的文本嵌入矩阵

        Returns:
            (mu, S_inv): 均值向量和协方差逆矩阵
        """
        mu = np.mean(embeddings, axis=0)
        # 使用 shrinkage 正则化避免协方差矩阵奇异
        S = np.cov(embeddings, rowvar=False)
        # Ledoit-Wolf shrinkage
        _n, D = embeddings.shape
        trace_S = np.trace(S)
        shrinkage = trace_S / D * 0.1
        S_reg = S + shrinkage * np.eye(D)
        try:
            S_inv = np.linalg.inv(S_reg)
        except np.linalg.LinAlgError:
            logger.warning("协方差矩阵求逆失败，回退到对角阵")
            S_inv = np.diag(1.0 / (np.diag(S) + 1e-8))
        return mu, S_inv

    def mahalanobis_distance(
        self, query_vec: np.ndarray, mu: np.ndarray, S_inv: np.ndarray
    ) -> float:
        """
        计算单个查询向量到语料库中心的 Mahalanobis 距离。

        论文公式 (3): d_qi = sqrt((x_qi - μ)^T · S^{-1} · (x_qi - μ))
        """
        diff = query_vec - mu
        return float(np.sqrt(diff @ S_inv @ diff))

    def compute_query_weights(
        self,
        query_embeddings: np.ndarray,
        mu: np.ndarray,
        S_inv: np.ndarray,
    ) -> List[int]:
        """
        计算每个 aspect query 的权重 k_qi。

        论文 Algorithm 1, Step 1:
        1. 计算 Mahalanobis 距离 d_qi
        2. 归一化: s_qi = (d_qi - d_min) / (d_max - d_min)
        3. 插值: k_qi = floor(K_max^(1-s) · K_min^s)

        Args:
            query_embeddings: shape (m, D) 的 aspect query 嵌入
            mu: 语料库均值向量
            S_inv: 协方差逆矩阵

        Returns:
            每个查询的权重 k_qi 列表
        """
        distances = np.array([
            self.mahalanobis_distance(q, mu, S_inv) for q in query_embeddings
        ])

        if len(distances) == 1 or distances.max() == distances.min():
            return [self.config.k_max] * len(distances)

        # 归一化到 [0, 1]
        d_min, d_max = distances.min(), distances.max()
        s_normalized = (distances - d_min) / (d_max - d_min)

        # 论文公式: k_qi = floor(K_max^(1-s) · K_min^s)
        weights = []
        for s in s_normalized:
            k = int(math.floor(
                (self.config.k_max ** (1.0 - s)) * (self.config.k_min ** s)
            ))
            k = max(self.config.k_min, min(self.config.k_max, k))
            weights.append(k)

        return weights

    def select_weight_points(
        self,
        query_embeddings: np.ndarray,
        corpus_embeddings: np.ndarray,
        weights: List[int],
    ) -> np.ndarray:
        """
        为每个 query 选择 k_qi 个最近邻点作为凸包顶点。

        论文 Algorithm 1, Step 2:
        R_Q ← f_weight(x_qi, k_qi, X_P)
        G = R_Q ∪ X_Q

        Returns:
            顶点集合 G, shape (l, D)
        """
        vertex_set = list(query_embeddings)  # 先放入 query 本身

        for i, q in enumerate(query_embeddings):
            k = weights[i]
            # 余弦相似度找最近邻
            norms_c = np.linalg.norm(corpus_embeddings, axis=1, keepdims=True)
            norms_q = np.linalg.norm(q)
            if norms_q < 1e-10:
                continue
            similarities = (corpus_embeddings @ q) / (norms_c.flatten() * norms_q + 1e-10)
            # 取 top-k 最近邻
            top_indices = np.argsort(-similarities)[:k]
            for idx in top_indices:
                vertex_set.append(corpus_embeddings[idx])

        return np.array(vertex_set)

    def umap_reduce(
        self,
        corpus_embeddings: np.ndarray,
        vertex_points: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        UMAP 降维。

        论文 Algorithm 1, Step 3:
        X_reduced ← f_UMAP(X_P)
        G_reduced ← f_UMAP(G)

        Returns:
            (corpus_reduced, vertices_reduced)

        Raises:
            RuntimeError: umap-learn 未安装时抛出
        """
        if not _check_umap_available():
            raise RuntimeError(
                "MAQ-Retrieval 的 UMAP 降维需要 umap-learn，"
                "请执行: pip install umap-learn"
            )

        import umap  # 懒加载：仅在实际调用时才触发 7s 初始化

        n_corpus = len(corpus_embeddings)
        all_data = np.vstack([corpus_embeddings, vertex_points])

        reducer = umap.UMAP(
            n_components=self.config.umap_n_components,
            n_neighbors=self.config.umap_n_neighbors,
            min_dist=self.config.umap_min_dist,
            metric=self.config.umap_metric,
            random_state=42,
        )
        all_reduced = reducer.fit_transform(all_data)

        corpus_reduced = all_reduced[:n_corpus]
        vertices_reduced = all_reduced[n_corpus:]

        return corpus_reduced, vertices_reduced

    def convex_hull_filter(
        self,
        corpus_reduced: np.ndarray,
        vertices_reduced: np.ndarray,
    ) -> np.ndarray:
        """
        构建凸包并过滤在凸包内部的文本。

        论文 Algorithm 1, Step 4:
        Conv(Q) = f_Quickhull(G_reduced)
        如果 x_pi 在 Conv(Q) 内 → 选中

        Returns:
            布尔数组，True 表示在凸包内
        """
        n_corpus = len(corpus_reduced)
        inside = np.zeros(n_corpus, dtype=bool)

        try:
            hull = ConvexHull(vertices_reduced)
        except QhullError:
            logger.warning("凸包构建失败（点太少或共面），回退到余弦距离过滤")
            # 回退：选离所有顶点质心最近的 top-N 个
            centroid = np.mean(vertices_reduced, axis=0)
            dists = np.linalg.norm(corpus_reduced - centroid, axis=1)
            top_n = min(len(corpus_reduced), max(10, len(vertices_reduced) * 2))
            top_indices = np.argsort(dists)[:top_n]
            inside[top_indices] = True
            return inside

        # 用凸包的半平面方程 Ax + b <= 0 判定内部点
        A = hull.equations[:, :-1]
        b = hull.equations[:, -1]

        for i in range(n_corpus):
            # 如果所有 Ax + b <= tolerance, 则在内部
            vals = A @ corpus_reduced[i] + b
            if np.all(vals <= 1e-6):
                inside[i] = True

        return inside

    def run(
        self,
        aspect_query_embeddings: np.ndarray,
        corpus_embeddings: np.ndarray,
    ) -> Tuple[np.ndarray, List[int], Dict[str, float]]:
        """
        执行完整的 MAQ-Retrieval 流程。

        Args:
            aspect_query_embeddings: (m, D) 四个 aspect 的 query embedding
            corpus_embeddings: (n, D) 语料库所有 chunk 的 embedding

        Returns:
            (inside_mask, weights, aspect_weight_dict)
            - inside_mask: 布尔数组，哪些 chunk 在凸包内
            - weights: 每个 aspect 的 k 值
            - aspect_weight_dict: {aspect_name: normalized_weight}
        """
        if len(corpus_embeddings) < self.config.umap_n_components + 2:
            if self.config.log_small_corpus_fallback:
                logger.warning(
                    "语料库太小 (%d chunks)，无法做 UMAP/ConvexHull，全部选中",
                    len(corpus_embeddings),
                )
            inside = np.ones(len(corpus_embeddings), dtype=bool)
            weights = [self.config.k_max] * len(aspect_query_embeddings)
            names = self.config.aspect_names[: len(weights)]
            total = sum(weights)
            w_dict = {n: w / total for n, w in zip(names, weights)}
            return inside, weights, w_dict

        # Step 1: 计算 Mahalanobis 权重
        mu, S_inv = self.compute_corpus_stats(corpus_embeddings)
        weights = self.compute_query_weights(aspect_query_embeddings, mu, S_inv)
        logger.info("MAQ 权重: %s", dict(zip(self.config.aspect_names, weights)))

        # Step 2: 选择权重点
        vertex_points = self.select_weight_points(
            aspect_query_embeddings, corpus_embeddings, weights
        )

        # Step 3: UMAP 降维
        corpus_reduced, vertices_reduced = self.umap_reduce(
            corpus_embeddings, vertex_points
        )

        # Step 4: 凸包过滤
        inside = self.convex_hull_filter(corpus_reduced, vertices_reduced)
        logger.info(
            "MAQ 凸包过滤: %d/%d chunks 被选中 (%.1f%%)",
            inside.sum(), len(inside), 100.0 * inside.sum() / max(1, len(inside)),
        )

        # 构建归一化权重字典
        names = self.config.aspect_names[: len(weights)]
        total = sum(weights)
        w_dict = {n: w / total for n, w in zip(names, weights)}

        return inside, weights, w_dict


# ============================================================
# 组件 2: SA-RAG 扩散引擎 (NetworkX 版)
# ============================================================


class SpreadingActivationEngine:
    """
    SA-RAG (Pavlović et al. 2025) 的 BFS 扩散算法，
    移植到 NetworkX 上运行，无需 Neo4j。

    核心公式:
    - 边权归一化: w' = max(0, (sim - c) / (1 - c))
    - 传播: a_j = min(1, a_j + Σ[a_i · w'_ij])
    - 过滤: a(u) > τ_a
    """

    def __init__(self, config: TOLFConfig):
        self.config = config

    def build_literature_graph(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: np.ndarray,
        similarity_threshold: float = 0.3,
    ) -> nx.Graph:
        """
        从文献 chunks 构建轻量 NetworkX 图。

        节点 = chunk，边 = chunk 间余弦相似度 > threshold。
        这替代了 SA-RAG 需要 Neo4j + NER/RE 的重型管道。

        Args:
            chunks: chunk 字典列表, 需含 'id' 和 'content'
            embeddings: (n, D) chunk 嵌入矩阵
            similarity_threshold: 建边的最低相似度

        Returns:
            NetworkX 图
        """
        G = nx.Graph()
        n = len(chunks)

        # 添加节点
        for i, chunk in enumerate(chunks):
            G.add_node(
                chunk.get("id", str(i)),
                content=chunk.get("content", ""),
                point_type=chunk.get("point_type", ""),
                embedding_idx=i,
            )

        # 归一化 embedding 计算余弦相似度矩阵
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-10)
        normalized = embeddings / norms

        # 计算上三角相似度矩阵（避免全量 n^2）
        node_ids = [chunk.get("id", str(i)) for i, chunk in enumerate(chunks)]

        for i in range(n):
            # 只计算 i 与后续节点的相似度
            if i + 1 < n:
                sims = normalized[i] @ normalized[i + 1:].T
                for j_offset, sim in enumerate(sims):
                    if sim >= similarity_threshold:
                        j = i + 1 + j_offset
                        G.add_edge(
                            node_ids[i],
                            node_ids[j],
                            similarity=float(sim),
                        )

        logger.info(
            "构建文献图: %d 节点, %d 边", G.number_of_nodes(), G.number_of_edges()
        )
        return G

    def create_adj_dict(
        self,
        G: nx.Graph,
    ) -> Dict[str, List[Tuple[str, float]]]:
        """
        创建邻接表, 边权按 SA-RAG 方式归一化。

        SA-RAG 原始做法: w' = max(0, (sim - c) / (1 - c))
        其中 sim 取建图时已缓存的余弦相似度。

        Returns:
            {node_id: [(neighbor_id, normalized_weight), ...]}
        """
        c = self.config.normalization_param  # 0.4
        adj = {}

        for node in G.nodes():
            adj[node] = []

        for u, v, data in G.edges(data=True):
            # 用边的 similarity 直接作为 SA-RAG 的边权
            raw_sim = data.get("similarity", 0.0)
            # SA-RAG 归一化: w' = max(0, (sim - c) / (1 - c))
            normalized_w = max(0.0, (raw_sim - c) / (1.0 - c))
            if normalized_w > 0:
                adj[u].append((v, normalized_w))
                adj[v].append((u, normalized_w))

        return adj

    def diffusion_process(
        self,
        adj_dict: Dict[str, List[Tuple[str, float]]],
        seed_nodes: List[str],
        initial_scores: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """
        BFS spreading activation (SA-RAG 核心算法)。

        SA-RAG 原论文 _diffusion_process:
            entity_score[target] = min(1, score + prob * parent_score)

        Args:
            adj_dict: 邻接表 {node: [(neighbor, weight), ...]}
            seed_nodes: 种子节点列表
            initial_scores: 种子节点初始分数，默认 1.0

        Returns:
            {node_id: activation_score}
        """
        entity_score = {e: 0.0 for e in adj_dict}

        # 多种子并行扩散：共享 entity_score，后续种子可叠加前序种子的激活能量
        for seed in seed_nodes:
            if seed not in entity_score:
                continue
            init_val = 1.0
            if initial_scores and seed in initial_scores:
                init_val = initial_scores[seed]
            entity_score[seed] = max(init_val, entity_score[seed])

            visited = set()
            queue = deque([seed])
            hops = {seed: 0}

            while queue:
                node = queue.popleft()
                if node in visited:
                    continue
                visited.add(node)

                current_hop = hops.get(node, 0)
                if current_hop >= self.config.k_hop:
                    continue

                for neighbor, weight in adj_dict.get(node, []):
                    # SA-RAG: a_j = min(1, a_j + w * a_i)
                    entity_score[neighbor] = min(
                        1.0,
                        entity_score[neighbor] + weight * entity_score[node],
                    )
                    if neighbor not in visited:
                        queue.append(neighbor)
                        if neighbor not in hops:
                            hops[neighbor] = current_hop + 1

        return entity_score

    def run(
        self,
        G: nx.Graph,
        seed_nodes: List[str],
        initial_scores: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """
        执行完整扩散流程。

        Args:
            G: 文献图（节点 = chunk, 边含 similarity 属性）
            seed_nodes: 种子节点列表
            initial_scores: 种子节点初始分数

        Returns:
            {node_id: activation_score}
        """
        adj_dict = self.create_adj_dict(G)
        scores = self.diffusion_process(adj_dict, seed_nodes, initial_scores)

        activated = {k: v for k, v in scores.items() if v > self.config.activation_threshold}
        logger.info(
            "扩散结果: %d/%d 节点被激活 (阈值 %.2f)",
            len(activated), len(scores), self.config.activation_threshold,
        )
        return scores


# ============================================================
# 组件 3: 证据门控
# ============================================================


class EvidenceGate:
    """
    证据质量 e(u) 门控。

    基于 point_type 基础分 + 数值证据/当前工作信号/hedging 惩罚
    计算轻量证据评分。与 scoring_engine.score_evidence（侧重图表/引用
    计数）互补，共同支撑门控条件: u ∈ Fish ⟺ a(u) > τ_a AND e(u) > τ_e
    """

    def __init__(self, config: TOLFConfig):
        self.config = config

    def compute_evidence_score(self, chunk: Dict[str, Any], query_tokens: Optional[set[str]] = None) -> float:
        """
        计算单个 chunk 的证据质量 e(u)。

        融合多个信号:
        - point_type 的证据等级
        - 是否有数值/图表/参考文献支撑
        - 当前工作 vs 文献引用
        - 查询词汇重叠（lexical grounding）
        """
        point_type = chunk.get("point_type", "discussion")

        # 基于 point_type 的基础分
        type_scores = {
            "result": 0.85,
            "mechanism": 0.75,
            "method": 0.50,
            "discussion": 0.55,
            "summary": 0.40,
            "background": 0.30,
            "meta": 0.05,
        }
        base = type_scores.get(point_type, 0.40)

        # 数值证据加分
        content = chunk.get("content", "")
        num_count = len(re.findall(
            r'\b\d+(?:\.\d+)?(?:\s*(?:%|wt\.%|μm|mm|nm|MPa|HV|°C|K))\b',
            content, re.I,
        ))
        num_bonus = min(0.15, num_count * 0.03)

        # 当前工作加分
        current_work = bool(re.search(
            r'\b(this study|this work|our|herein|present work)\b',
            content, re.I,
        ))
        current_bonus = 0.10 if current_work else 0.0

        # hedging 惩罚
        hedge = bool(re.search(
            r'\b(may|might|could|suggest|likely|potentially)\b',
            content, re.I,
        ))
        hedge_penalty = 0.10 if hedge else 0.0

        # 查询词汇重叠加分（lexical grounding）
        lexical_bonus = 0.0
        if query_tokens:
            content_lower = content.lower()
            overlap_count = sum(1 for token in query_tokens if token in content_lower)
            if overlap_count > 0:
                lexical_bonus = min(0.20, overlap_count * 0.05)

        score = min(1.0, base + num_bonus + current_bonus + lexical_bonus - hedge_penalty)
        return round(score, 4)

    def gate(
        self,
        activation_scores: Dict[str, float],
        chunks: List[Dict[str, Any]],
        query_tokens: Optional[set[str]] = None,
    ) -> List[FishResult]:
        """
        执行证据门控 = 激活分 + 证据质量双阈值过滤。

        u ∈ Fish ⟺ a(u) > τ_a AND e(u) > τ_e

        Returns:
            FishResult 列表 (已按 activation_score 降序排列)
        """
        results = []
        for chunk in chunks:
            cid = chunk.get("id", "")
            a_score = activation_scores.get(cid, 0.0)
            e_score = self.compute_evidence_score(chunk, query_tokens=query_tokens)

            fish = FishResult(
                chunk_id=cid,
                activation_score=a_score,
                evidence_score=e_score,
                aspect_weights={},
                point_type=chunk.get("point_type", ""),
                in_convex_hull=chunk.get("in_convex_hull", False),
                content=chunk.get("content", "")[:300],
            )

            if a_score > self.config.activation_threshold and \
               e_score > self.config.evidence_threshold:
                results.append(fish)

        results.sort(key=lambda r: r.activation_score, reverse=True)
        logger.info(
            "证据门控: %d/%d chunks 通过 (τ_a=%.2f, τ_e=%.2f)",
            len(results), len(chunks),
            self.config.activation_threshold, self.config.evidence_threshold,
        )
        return results


# ============================================================
# 主引擎: TOLF Pipeline
# ============================================================


class TOLFEngine:
    """
    TOLF 全流程引擎。

    Pipeline:
    1. 生成四层 aspect query embedding (K/S/R/V)
    2. MAQ 权重 → 凸包过滤
    3. 构建文献图 → 扩散传播
    4. 证据门控 → 输出 Fish 列表
    """

    def __init__(self, config: Optional[TOLFConfig] = None):
        self.config = config or TOLFConfig()
        self.maq = MAQWeightEngine(self.config)
        self.diffusion = SpreadingActivationEngine(self.config)
        self.gate = EvidenceGate(self.config)

    def generate_aspect_queries(self, goal: str) -> Dict[str, str]:
        """
        将用户目标分解为 K/S/R/V 四层 aspect query。

        K (Knowledge): 背景知识层 — "关于...的已有研究背景和理论基础"
        S (Structure): 结构层 — "...的组织结构和微观形貌特征"
        R (Result):    结果层 — "...的实验结果和性能数据"
        V (Value):     价值层 — "...的作用机理和因果解释"
        """
        templates = {
            "knowledge": "关于{goal}的已有研究背景、理论基础和文献综述",
            "structure": "{goal}的实验方法、工艺参数和组织结构特征",
            "result": "{goal}的实验结果、性能数据和定量测量",
            "value": "{goal}的作用机理、因果解释和理论价值",
        }
        return {k: v.format(goal=goal) for k, v in templates.items()}

    def compute_initial_activation(
        self,
        chunk_embeddings: np.ndarray,
        aspect_query_embeddings: np.ndarray,
        aspect_weights: Dict[str, float],
        chunk_ids: List[str],
    ) -> Dict[str, float]:
        """
        计算初始激活值 a_0(u) = α·f_K(u) + β·f_S(u) + γ·f_R(u) + δ·f_V(u)

        其中 f_X(u) = cos_sim(chunk_embedding, aspect_X_embedding)
        """
        # 归一化
        c_norms = np.linalg.norm(chunk_embeddings, axis=1, keepdims=True)
        c_norms = np.maximum(c_norms, 1e-10)
        c_normalized = chunk_embeddings / c_norms

        q_norms = np.linalg.norm(aspect_query_embeddings, axis=1, keepdims=True)
        q_norms = np.maximum(q_norms, 1e-10)
        q_normalized = aspect_query_embeddings / q_norms

        # sim_matrix: (n_chunks, m_aspects)
        sim_matrix = c_normalized @ q_normalized.T

        # 加权求和
        names = self.config.aspect_names[:len(aspect_query_embeddings)]
        weights_array = np.array([aspect_weights.get(n, 0.25) for n in names])

        # a_0(u) = Σ w_i * sim(u, q_i)
        initial_scores = sim_matrix @ weights_array

        # 裁剪到 [0, 1]
        initial_scores = np.clip(initial_scores, 0.0, 1.0)

        return {cid: float(initial_scores[i]) for i, cid in enumerate(chunk_ids)}

    def find_seed_nodes(
        self,
        initial_scores: Dict[str, float],
        top_k: int = 5,
    ) -> List[str]:
        """选初始激活值最高的 top_k 个节点作为扩散种子"""
        sorted_nodes = sorted(
            initial_scores.items(), key=lambda x: x[1], reverse=True
        )
        return [n for n, _ in sorted_nodes[:top_k]]

    def maybe_apply_representative_rerank(
        self,
        goal: str,
        results: List[FishResult],
        *,
        representative_reranker: Optional[RepresentativeReranker] = None,
        enable_representative_rerank: bool = False,
    ) -> List[FishResult]:
        """在 evidence gate 之后预留代表单元精排接口。

        默认关闭；仅当明确传入 callback 且 `enable_representative_rerank=True`
        时才生效。这样 reranker 仍是 TOLF 架构中的一等 stage，但不会默认
        接入主链或 text-only pilot。
        """
        if not enable_representative_rerank or representative_reranker is None:
            return results

        reranked = representative_reranker(goal, list(results))
        if not isinstance(reranked, list):
            raise TypeError("representative_reranker must return a list of FishResult")

        logger.info(
            "代表单元 rerank 已执行: goal='%s', input=%d, output=%d",
            goal[:30],
            len(results),
            len(reranked),
        )
        return reranked

    def run(
        self,
        goal: str,
        chunks: List[Dict[str, Any]],
        embeddings: np.ndarray,
        aspect_query_embeddings: Optional[np.ndarray] = None,
        representative_reranker: Optional[RepresentativeReranker] = None,
        enable_representative_rerank: bool = False,
    ) -> List[FishResult]:
        """
        执行完整 TOLF 捕捞流程。

        Args:
            goal: 用户目标描述
            chunks: chunk 字典列表, 每个需含 'id', 'content', 可选 'point_type'
            embeddings: (n, D) chunk 嵌入矩阵
            aspect_query_embeddings: (4, D) 四层 aspect 的嵌入，
                                     若为 None 则跳过 MAQ 凸包过滤，均匀权重

        Returns:
            FishResult 列表 (已过双阈值门控, 按激活分降序)
        """
        n_chunks = len(chunks)
        if n_chunks == 0:
            return []

        chunk_ids = [c.get("id", str(i)) for i, c in enumerate(chunks)]
        chunk_id_to_idx = {cid: i for i, cid in enumerate(chunk_ids)}

        # --- Step 0: 生成 aspect queries ---
        aspect_queries = self.generate_aspect_queries(goal)
        logger.info("四层 aspect queries 已生成: %s", list(aspect_queries.keys()))

        # --- Step 1: MAQ 权重 + 凸包过滤 ---
        if aspect_query_embeddings is None:
            logger.warning("未提供 aspect_query_embeddings, 跳过 MAQ 凸包过滤")
            inside_mask = np.ones(n_chunks, dtype=bool)
            aspect_weights = {n: 0.25 for n in self.config.aspect_names}
        else:
            inside_mask, _raw_weights, aspect_weights = self.maq.run(
                aspect_query_embeddings, embeddings
            )

        # 标记 chunks
        for i, chunk in enumerate(chunks):
            chunk["in_convex_hull"] = bool(inside_mask[i])

        # --- Step 2: 计算初始激活值 ---
        if aspect_query_embeddings is not None:
            initial_scores = self.compute_initial_activation(
                embeddings, aspect_query_embeddings, aspect_weights, chunk_ids
            )
        else:
            initial_scores = {cid: 0.5 for cid in chunk_ids}

        # --- Step 3: 构建图 + 扩散 ---
        G = self.diffusion.build_literature_graph(
            chunks, embeddings, similarity_threshold=0.3
        )
        seed_nodes = self.find_seed_nodes(initial_scores, top_k=5)
        logger.info("种子节点: %s", seed_nodes[:5])

        activation_scores = self.diffusion.run(
            G,
            seed_nodes,
            initial_scores,
        )

        # 凸包外的 chunk 激活值衰减
        for cid in chunk_ids:
            if not inside_mask[chunk_id_to_idx[cid]]:
                activation_scores[cid] = activation_scores.get(cid, 0.0) * 0.5

        # --- Step 4: 证据门控（含 lexical grounding）---
        query_tokens = set(_TOKEN_RE.findall(goal.lower()))
        results = self.gate.gate(activation_scores, chunks, query_tokens=query_tokens)

        # 填入 aspect_weights
        for r in results:
            r.aspect_weights = aspect_weights

        results = self.maybe_apply_representative_rerank(
            goal,
            results,
            representative_reranker=representative_reranker,
            enable_representative_rerank=enable_representative_rerank,
        )

        logger.info(
            "TOLF 完成: 目标='%s', 输入 %d chunks, 捕获 %d fish",
            goal[:30], n_chunks, len(results),
        )
        return results
