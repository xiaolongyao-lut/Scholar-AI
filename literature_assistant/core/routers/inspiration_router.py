# -*- coding: utf-8 -*-
"""Inspiration API Router — 启发点生成与续写上下文"""

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from llm_cost_logger import log_llm_call
from llm_defaults import resolve_llm_params
from llm_pricing import usage_from_response
from project_paths import output_path
from sampling_storage import load_user_sampling

from routers.chat_router import LLMConfig, _build_chat_request, _extract_chat_response

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
    output_root = output_path()
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
    llm: LLMConfig | None = Field(None, description="Optional LLM config for real inspiration generation")
    sampling: dict[str, float | int] | None = Field(default=None, description="Per-task sampling overrides")


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


def _resolve_inspiration_llm_config(
    llm: LLMConfig,
    sampling: dict[str, float | int] | None,
) -> LLMConfig:
    file_overrides = (load_user_sampling() or {}).get("inspiration", {})
    merged: dict[str, float | int] = {}
    if isinstance(file_overrides, dict):
        merged.update(file_overrides)
    if sampling:
        merged.update(sampling)
    resolved = resolve_llm_params("inspiration", merged or None)
    return llm.model_copy(
        update={
            "temperature": float(resolved["temperature"]),
            "top_p": float(resolved["top_p"]),
            "top_k": int(resolved["top_k"]),
            "max_tokens": int(resolved["max_tokens"]),
        }
    )


def _log_inspiration_telemetry(
    *,
    model: str | None,
    started_at: float,
    usage: dict[str, Any] | None = None,
    response: Any = None,
    status: str = "ok",
) -> None:
    try:
        usage_row = usage or usage_from_response(response)
        log_llm_call(
            model=model,
            task="inspiration",
            prompt_tokens=int(usage_row.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage_row.get("completion_tokens", 0) or 0),
            latency_ms=(time.perf_counter() - started_at) * 1000,
            status=status,
            cache_status="miss",
            decision="invoke",
        )
    except Exception:
        pass


def _build_inspiration_prompt(query: str, limit: int) -> str:
    return (
        f"请围绕研究主题“{query}”生成 {limit} 条中文写作启发点。\n"
        "只返回 JSON 对象，不要 Markdown。\n"
        "格式：{\"sparks\":[{\"content\":\"1-2 句启发\",\"spark_type\":\"causal_extension|conflict|analogy|gap|synthesis|memory_association\","
        "\"source_papers\":[\"若未知则空数组\"],\"confidence\":0.0,\"related_point_ids\":[],\"actionable\":true}]}"
    )


def _coerce_llm_sparks(answer: str, limit: int) -> list[SparkResponse]:
    from inspiration_engine import _spark_id

    payload = json.loads(answer)
    items = payload.get("sparks") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("missing sparks list")

    sparks: list[SparkResponse] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            raise ValueError("invalid spark item")
        content = str(item.get("content") or "").strip()
        if not content:
            raise ValueError("spark content required")
        raw_sources = item.get("source_papers") or []
        source_papers = [str(source).strip() for source in raw_sources if str(source).strip()] if isinstance(raw_sources, list) else []
        raw_related = item.get("related_point_ids") or []
        related_point_ids = [str(value).strip() for value in raw_related if str(value).strip()] if isinstance(raw_related, list) else []
        try:
            confidence = float(item.get("confidence", 0.6))
        except (TypeError, ValueError):
            confidence = 0.6
        sparks.append(
            SparkResponse(
                id=str(item.get("id") or _spark_id(content)),
                content=content,
                spark_type=str(item.get("spark_type") or "analogy"),
                source_papers=source_papers,
                confidence=max(0.0, min(1.0, confidence)),
                related_point_ids=related_point_ids,
                actionable=bool(item.get("actionable", True)),
            )
        )
    return sparks


def _generate_local_sparks(req: GenerateSparksRequest, engine) -> list[Any]:
    sparks = engine.generate_sparks(req.query, limit=req.limit)

    if not sparks and req.project_id:
        try:
            from routers.resources_router import _ensure_project_chunks  # noqa: PLC0415
            chunk_store = _ensure_project_chunks(req.project_id)
            all_chunks = [c for chunks in chunk_store.values() for c in chunks]
            if all_chunks:
                sparks = engine.generate_sparks_from_chunks(req.query, all_chunks, limit=req.limit)
        except Exception:  # noqa: BLE001
            logger.warning("从项目知识库生成启发点失败，跳过")
    return sparks


async def _generate_llm_sparks(req: GenerateSparksRequest) -> list[SparkResponse] | None:
    if req.llm is None:
        return None

    llm = _resolve_inspiration_llm_config(req.llm, req.sampling)
    prompt = _build_inspiration_prompt(req.query, req.limit)
    url, headers, payload = _build_chat_request(
        prompt,
        [],
        llm,
        response_format={"type": "json_object"},
    )
    telemetry_model = str(payload.get("model", llm.model))
    started_at = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        answer, usage, model_used = _extract_chat_response(data, llm.provider, telemetry_model)
        sparks = _coerce_llm_sparks(answer, req.limit)
        _log_inspiration_telemetry(
            model=model_used or telemetry_model,
            started_at=started_at,
            usage=usage,
            status="ok",
        )
        return sparks
    except Exception as exc:
        _log_inspiration_telemetry(
            model=telemetry_model,
            started_at=started_at,
            status="error",
        )
        logger.warning("LLM inspiration failed, falling back to local engine: %s", exc)
        return None


# --- Endpoints ---

@router.post("/generate", response_model=GenerateSparksResponse)
async def generate_inspirations(req: GenerateSparksRequest):
    """基于查询生成启发点列表。"""
    engine = _get_engine()
    llm_sparks = await _generate_llm_sparks(req)
    if llm_sparks is not None:
        return GenerateSparksResponse(sparks=llm_sparks, total=len(llm_sparks))

    sparks = _generate_local_sparks(req, engine)

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
