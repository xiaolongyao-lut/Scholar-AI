# -*- coding: utf-8 -*-
"""
Unified Chunking Pipeline
Role: 整合规则切分 + LLM 上下文增强 + 质量守卫 + 向量化
"""

from __future__ import annotations

import logging
import importlib.util
from collections.abc import Callable
from typing import Any, Dict, List, Optional

from chunk_models import EnrichedChunk
from chunk_size_guard import inspect_text
from contextual_chunker import batch_contextualize
from project_paths import EXTERNAL_REFERENCES_ROOT

logger = logging.getLogger(__name__)


SplitFunction = Callable[[str, int, int, Optional[Dict[str, Any]]], List[Dict[str, Any]]]


def _fallback_split_text_with_metadata(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    base_metadata: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Split text locally when the reference splitter is unavailable."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be non-negative")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    metadata = dict(base_metadata or {})
    if not text:
        return [{"content": "", "metadata": metadata}]

    chunks: List[Dict[str, Any]] = []
    step = chunk_size - chunk_overlap
    for start in range(0, len(text), step):
        content = text[start:start + chunk_size]
        if not content:
            continue
        chunks.append({"content": content, "metadata": metadata})
        if start + chunk_size >= len(text):
            break
    return chunks


def _load_reference_splitter() -> SplitFunction:
    """Load the reference splitter from the vendored Rag_System project."""

    splitter_path = (
        EXTERNAL_REFERENCES_ROOT
        / "Rag_System-main"
        / "backend"
        / "app"
        / "services"
        / "chunk_splitter.py"
    )
    if not splitter_path.is_file():
        logger.warning("Reference chunk splitter not found: %s", splitter_path)
        return _fallback_split_text_with_metadata

    spec = importlib.util.spec_from_file_location("rag_system_reference_chunk_splitter", splitter_path)
    if spec is None or spec.loader is None:
        logger.warning("Reference chunk splitter cannot be loaded: %s", splitter_path)
        return _fallback_split_text_with_metadata

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    splitter = getattr(module, "split_text_with_metadata", None)
    if not callable(splitter):
        logger.warning("Reference chunk splitter has no split_text_with_metadata function")
        return _fallback_split_text_with_metadata
    return splitter


split_text_with_metadata = _load_reference_splitter()


class ChunkingPipeline:
    """统一切块流水线"""

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        enable_contextual: bool = True,
        enable_guard: bool = True
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.enable_contextual = enable_contextual
        self.enable_guard = enable_guard

    def run(
        self,
        text: str,
        material_id: str,
        base_metadata: Optional[Dict[str, Any]] = None
    ) -> List[EnrichedChunk]:
        """执行完整切块流水线"""
        logger.info(f"开始切块流水线: material_id={material_id}")

        # 1. 规则切分 (GitHub 设计)
        raw_chunks = split_text_with_metadata(
            text,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            base_metadata=base_metadata
        )

        # 2. 转换数据模型并执行守卫 (DoD §3.8)
        enriched_chunks: List[EnrichedChunk] = []
        for i, raw in enumerate(raw_chunks):
            content = raw["content"]

            if self.enable_guard:
                metrics = inspect_text(content)
                if metrics["is_oversize"]:
                    logger.warning(f"Chunk #{i} 超大: {metrics['token_count']} tokens, 已标记")

            enriched_chunks.append(EnrichedChunk(
                chunk_id=f"{material_id}#{i}",
                material_id=material_id,
                title=str(raw.get("metadata", {}).get("title", "")),
                section_title="",
                chunk_index=i,
                content=content,
                raw_content=content,
                chunk_type="text",
                char_count=len(content)
            ))

        # 3. LLM 上下文增强
        if self.enable_contextual:
            logger.info("执行 LLM 上下文增强...")
            # batch_contextualize 会为每个 chunk 添加 document-level context
            # 注意：contextual_chunker.py 中的 batch_contextualize 期望的是 list[dict]
            chunks_as_dicts = [
                {"chunk_id": c.chunk_id, "content": c.content, "material_id": c.material_id}
                for c in enriched_chunks
            ]
            contextualized = batch_contextualize(chunks_as_dicts)

            # 将增强后的内容写回对象
            for i, c in enumerate(enriched_chunks):
                if i < len(contextualized):
                    c.content = contextualized[i].get("content", c.content)

        logger.info(f"切块流水线完成: 生成 {len(enriched_chunks)} 个切块")
        return enriched_chunks

def get_chunking_pipeline(**kwargs) -> ChunkingPipeline:
    """流水线单例/工厂"""
    return ChunkingPipeline(**kwargs)
