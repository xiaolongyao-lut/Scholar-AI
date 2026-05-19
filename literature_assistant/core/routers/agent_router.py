# -*- coding: utf-8 -*-
"""Agent API Router — AI 调度引擎 API"""

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger("AgentRouter")
router = APIRouter(prefix="/agent", tags=["Agent"])

_engine_instance = None


def _get_engine():
    """延迟初始化 AIEngine 并注册默认工具。"""
    global _engine_instance
    if _engine_instance is not None:
        return _engine_instance

    from layers.a_layer_agent_coordinator import create_default_engine

    # 收集可用组件
    mempalace = None
    try:
        from python_adapter_server import get_memory_adapter
        mem = get_memory_adapter()
        if mem is not None and mem.is_enabled():
            mempalace = mem
    except Exception as exc:
        logger.warning("MemPalace adapter unavailable for /agent/tools: %s", exc)

    inspiration_engine = None
    try:
        from routers.inspiration_router import _get_engine as get_insp
        inspiration_engine = get_insp()
    except Exception:
        pass

    conflict_detector = None
    try:
        from layers.w_layer_cross_paper_analysis import ConflictDetector
        conflict_detector = ConflictDetector()
    except Exception:
        pass

    _engine_instance = create_default_engine(
        mempalace=mempalace,
        inspiration_engine=inspiration_engine,
        conflict_detector=conflict_detector,
    )
    return _engine_instance


class DispatchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000, description="用户查询/意图")


class DispatchResponse(BaseModel):
    query: str
    tool_calls: list[dict[str, Any]] = []
    results: list[Any] = []
    summary: str = ""


@router.post("/dispatch", response_model=DispatchResponse)
async def agent_dispatch(req: DispatchRequest):
    """AI 自由调度：根据用户意图调用合适的工具组合。"""
    engine = _get_engine()
    result = engine.dispatch(req.query)
    return DispatchResponse(**result.to_dict())


@router.get("/tools")
async def list_tools():
    """列出所有已注册的工具及其描述。"""
    engine = _get_engine()
    return {
        "tools": engine.get_tool_descriptions(),
        "llm_available": engine.has_llm,
    }
