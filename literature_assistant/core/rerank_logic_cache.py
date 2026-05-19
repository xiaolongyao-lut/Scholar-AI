# -*- coding: utf-8 -*-
"""
Rerank Result Durable Cache
Role: 缓存 (Query + Candidates) 到重排后分数的映射，保护高价 API
Spec: RAG_ADVANCED_EVOLUTION.md §2.2
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from project_paths import output_path

logger = logging.getLogger(__name__)

class RerankDurableCache:
    """持久化 Rerank 缓存：基于候选集 ID 序列生成的稳定指纹"""

    def __init__(self, cache_dir: str | Path | None = None):
        self.cache_dir = Path(cache_dir) if cache_dir is not None else output_path("rerank_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _make_key(self, query: str, candidates: List[Dict[str, Any]]) -> str:
        # 1. 提取 ID 并排序，保证 Key 的稳定性
        ids = sorted([str(c.get("chunk_id") or c.get("id", "")) for c in candidates])

        # 2. 结合 Query 文本
        material = f"{query.strip()}||{','.join(ids)}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def lookup(self, query: str, candidates: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        """尝试从磁盘加载已排序的结果"""
        key = self._make_key(query, candidates)
        cache_path = self.cache_dir / f"{key}.json"

        if cache_path.exists():
            try:
                logger.info(f"⚡ Rerank 磁盘缓存命中: {key[:12]}")
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"读取 Rerank 缓存失败: {e}")
        return None

    def update(self, query: str, candidates: List[Dict[str, Any]], results: List[Dict[str, Any]]):
        """保存重排后的结果"""
        key = self._make_key(query, candidates)
        cache_path = self.cache_dir / f"{key}.json"

        try:
            # 原子写入
            tmp_path = cache_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp_path, cache_path)
        except Exception as e:
            logger.error(f"持久化 Rerank 缓存失败: {e}")

def get_rerank_cache() -> RerankDurableCache:
    return RerankDurableCache()
