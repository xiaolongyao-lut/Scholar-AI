# -*- coding: utf-8 -*-
"""
Industrial Semantic Cache for RAG
Role: 基于向量相似度的问答防火墙，实现零冗余地址开销
Spec: RAG_ADVANCED_EVOLUTION.md §2.1
"""

from __future__ import annotations

import json
import logging
import os
import hashlib
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

class SemanticCache:
    """语义缓存层：拦截逻辑等价的重复查询"""

    def __init__(
        self,
        cache_dir: str | Path = "output/semantic_cache",
        threshold: float = 0.985,
        dimension: int = 1024
    ):
        self.cache_dir = Path(cache_dir)
        self.threshold = threshold
        self.dimension = dimension
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.vec_file = self.cache_dir / "query_vectors.npy"
        self.data_file = self.cache_dir / "responses.jsonl"

        # 内存镜像
        self._vectors: np.ndarray = np.zeros((0, dimension), dtype=np.float32)
        self._responses: list[dict[str, Any]] = []
        self._load()

    def _load(self):
        """同步加载缓存到内存"""
        if self.vec_file.exists() and self.data_file.exists():
            try:
                self._vectors = np.load(str(self.vec_file))
                with self.data_file.open("r", encoding="utf-8") as f:
                    self._responses = [json.loads(line) for line in f]
                logger.info(f"💾 加载了 {len(self._responses)} 条语义缓存记录")
            except Exception as e:
                logger.warning(f"语义缓存加载失败，将重建: {e}")
                self._reset()

    def _reset(self):
        self._vectors = np.zeros((0, self.dimension), dtype=np.float32)
        self._responses = []

    def lookup(
        self,
        query_vec: np.ndarray,
        corpus_hash: str,
        model_id: str
    ) -> Optional[str]:
        """
        语义查找：
        1. 检查向量相似度
        2. 校验语料指纹和模型一致性
        """
        if self._vectors.shape[0] == 0:
            return None

        # 计算余弦相���度
        norm_q = query_vec / (np.linalg.norm(query_vec) + 1e-9)
        norm_vs = self._vectors / (np.linalg.norm(self._vectors, axis=1, keepdims=True) + 1e-9)
        scores = np.dot(norm_vs, norm_q)

        best_idx = np.argmax(scores)
        if scores[best_idx] >= self.threshold:
            hit = self._responses[best_idx]
            # 严格性核查：语料库或模型变了则缓存失效
            if hit.get("corpus_hash") == corpus_hash and hit.get("model") == model_id:
                logger.info(f"✨ 语义缓存命中! score={scores[best_idx]:.4f}")
                return hit.get("response")

        return None

    def update(
        self,
        query_vec: np.ndarray,
        query_text: str,
        response: str,
        corpus_hash: str,
        model_id: str
    ):
        """原子化更新缓存记录"""
        new_entry = {
            "query": query_text,
            "response": response,
            "corpus_hash": corpus_hash,
            "model": model_id,
            "timestamp": hashlib.md5(query_text.encode()).hexdigest() # 简化版ID
        }

        # 内存更新
        self._vectors = np.vstack([self._vectors, query_vec.astype(np.float32)])
        self._responses.append(new_entry)

        # 磁盘更新 (原子重写)
        try:
            tmp_vec = self.vec_file.with_suffix(".npy.tmp")
            tmp_data = self.data_file.with_suffix(".jsonl.tmp")

            np.save(str(tmp_vec), self._vectors)
            with tmp_data.open("w", encoding="utf-8") as f:
                for res in self._responses:
                    f.write(json.dumps(res, ensure_ascii=False) + "\n")

            os.replace(tmp_vec, self.vec_file)
            os.replace(tmp_data, self.data_file)
        except Exception as e:
            logger.error(f"持久化语义缓存失败: {e}")
