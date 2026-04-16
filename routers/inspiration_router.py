# -*- coding: utf-8 -*-
"""Inspiration API Router — 启发点生成与续写上下文"""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("InspirationRouter")
router = APIRouter(prefix="/inspiration", tags=["Inspiration"])

# Lazy singleton
_engine_instance = None


def _get_engine():
    """延迟初始化 InspirationEngine，自动加载已有因果 DAG 和 MemPalace。"""
    global _engine_instance
    if _engine_instance is not None:
        return _engine_instance

    from inspiration_engine import InspirationEngine, load_causal_dags_from_output

    # 加载因果 DAG
    output_root = Path("output")
    causal_dags = []
    if output_root.is_dir():
        causal_dags = load_causal_dags_from_output(output_root)

    # 加载 MemPalace（可选）
    mempalace = None
    try:
        from layers.m_layer_mempalace_memory import MempalaceAdapter
        mem = MempalaceAdapter()
        if mem.is_enabled():
            mempalace = mem
    except Exception:
        pass

    # 加载冲突检测器（可选）
    conflict_detector = None
    try:
        from layers.w_layer_cross_paper_analysis import ConflictDetector
        conflict_detector = ConflictDetector()
    except Exception:
        pass

    _engine_instance = InspirationEngine(
        mempalace=mempalace,
        causal_dags=causal_dags,
        conflict_detector=conflict_detector,
    )
    return _engine_instance


def reload_engine():
    """外部调用以重新加载引擎（例如新论文入库后）。"""
    global _engine_instance
    _engine_instance = None


# --- Request / Response Models ---

class GenerateSparksRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="查询/主题")
    limit: int = Field(10, ge=1, le=50, description="最大返回数")
    project_id: str | None = Field(None, description="项目ID，用于从知识库生成启发点")


class SparkResponse(BaseModel):
    id: str
    content: str
    spark_type: str
    source_papers: list[str] = []
    confidence: float = 0.0
    related_point_ids: list[str] = []
    actionable: bool = True


class GenerateSparksResponse(BaseModel):
    sparks: list[SparkResponse]
    total: int


class ContinuationResponse(BaseModel):
    spark: SparkResponse
    evidence_texts: list[str] = []
    causal_chain_summary: str = ""
    suggested_angles: list[str] = []
    related_figures: list[str] = []


# --- Endpoints ---

@router.post("/generate", response_model=GenerateSparksResponse)
async def generate_inspirations(req: GenerateSparksRequest):
    """基于查询生成启发点列表。"""
    engine = _get_engine()
    sparks = engine.generate_sparks(req.query, limit=req.limit)

    # 降级：若无 DAG/MemPalace 数据，从项目知识库切片生成启发点
    if not sparks and req.project_id:
        try:
            from routers.resources_router import _ensure_project_chunks  # noqa: PLC0415
            chunk_store = _ensure_project_chunks(req.project_id)
            all_chunks = [c for chunks in chunk_store.values() for c in chunks]
            if all_chunks:
                sparks = engine.generate_sparks_from_chunks(req.query, all_chunks, limit=req.limit)
        except Exception:  # noqa: BLE001
            logger.warning("从项目知识库生成启发点失败，跳过")

    return GenerateSparksResponse(
        sparks=[SparkResponse(**s.to_dict()) for s in sparks],
        total=len(sparks),
    )


@router.get("/{spark_id}/context", response_model=ContinuationResponse)
async def get_spark_context(spark_id: str):
    """获取启发点的续写上下文。"""
    engine = _get_engine()
    ctx = engine.get_continuation_context(spark_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"启发点不存在或已过期: {spark_id}")
    d = ctx.to_dict()
    return ContinuationResponse(
        spark=SparkResponse(**d["spark"]),
        evidence_texts=d["evidence_texts"],
        causal_chain_summary=d["causal_chain_summary"],
        suggested_angles=d["suggested_angles"],
        related_figures=d["related_figures"],
    )


@router.post("/reload")
async def reload_inspiration_engine():
    """重新加载启发引擎（例如新论文入库后调用）。"""
    reload_engine()
    return {"status": "ok", "message": "InspirationEngine 已重新加载"}
