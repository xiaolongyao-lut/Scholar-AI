# -*- coding: utf-8 -*-
"""Debug-only chat endpoint exposing retrieval trace.

P1.0 spike (per ``docs/plans/active/2026-05-09-rag-pro-borrow-features.md``):
returns ``query / retrieval candidates / selected / metrics / trace_id`` only.
No LLM generation, no session persistence, no research-profile updates.

Reuses private helpers from ``intelligent_chat_router`` by design — a future
P1.1 refactor will extract them into a shared ``chat_context_helpers`` module.
"""

from __future__ import annotations

import time
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dev_flags import is_dev_mode_enabled
from routers.intelligent_chat_router import (
    ContextChunkPayload,
    ContextTier,
    _build_context_chunks,
    _build_context_strings,
    _build_project_context_chunks,
    _resolve_source_paths,
    _validate_project_id,
)


router = APIRouter(prefix="/api", tags=["Chat"])


_PREVIEW_CHAR_LIMIT = 300
_DEFAULT_TOP_K = 20
_PROMPT_PREVIEW_LIMIT = 1000


class ChatDebugRequest(BaseModel):
    """Request payload for the debug chat endpoint."""

    query: str = Field(..., min_length=1, max_length=5000)
    project_id: str | None = None
    source_paths: list[str] | None = None
    tier: ContextTier = "balanced"
    top_k: int = Field(_DEFAULT_TOP_K, ge=1, le=50)
    include_generation: bool = Field(
        default=False,
        description="P1.0 spike: ignored (always false). P1.1 will honor this.",
    )
    include_full_prompt: bool = Field(
        default=False,
        description="Return raw prompt_template (sensitive). Requires LITERATURE_DEV_MODE.",
    )
    persist_trace: bool = Field(
        default=False,
        description="P1.0 spike: ignored (always false). P1.1 will write to runtime_state if enabled.",
    )


class DebugChunk(BaseModel):
    """Trace-friendly view of a context chunk (preview-truncated)."""

    chunk_id: str | None = None
    material_id: str | None = None
    content_preview: str = Field(..., max_length=_PREVIEW_CHAR_LIMIT)
    relevance_score: float | None = None
    source: str
    page: int | str | None = None
    section: str | None = None
    source_labels: list[str] = Field(default_factory=list)


class RejectedChunk(BaseModel):
    """Chunk that was retrieved but did not enter the final context."""

    chunk_id: str
    reason: Literal["rank", "budget", "filter"]


class DebugMetrics(BaseModel):
    """Per-stage timing and (future) token usage."""

    query_rewrite_time_ms: float | None = None
    retrieval_time_ms: float = Field(..., ge=0.0)
    rerank_time_ms: float | None = None
    prompt_build_time_ms: float = Field(..., ge=0.0)
    generation_time_ms: float | None = None
    total_time_ms: float = Field(..., ge=0.0)
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


ConfidenceLabel = Literal["high", "medium", "low", "very_low"]


class ChatDebugResponse(BaseModel):
    """Response envelope for the debug chat endpoint."""

    trace_id: str
    query: str
    rewritten_query: str | None = None
    retrieval_results: list[DebugChunk] = Field(default_factory=list)
    selected_chunks: list[DebugChunk] = Field(default_factory=list)
    rejected_chunks: list[RejectedChunk] = Field(default_factory=list)
    prompt_preview: str = ""
    prompt_template: str | None = None
    answer: str | None = None
    confidence_score: float | None = None
    confidence_label: ConfidenceLabel | None = None
    metrics: DebugMetrics


def _truncate_preview(text: str, limit: int = _PREVIEW_CHAR_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _to_debug_chunks(chunks: list[ContextChunkPayload]) -> list[DebugChunk]:
    return [
        DebugChunk(
            chunk_id=c.chunk_id,
            material_id=c.material_id,
            content_preview=_truncate_preview(c.content),
            relevance_score=c.relevance_score,
            source=c.source,
            page=c.page,
            section=c.section_title,
            source_labels=list(c.source_labels),
        )
        for c in chunks
    ]


@router.post("/chat/debug", response_model=ChatDebugResponse)
async def chat_debug(req: ChatDebugRequest) -> ChatDebugResponse:
    """Return retrieval trace for the Test Chat panel.

    P1.0 spike behavior: no generation, no persistence, no profile update.
    """
    trace_id = f"trace_{uuid.uuid4().hex[:12]}"
    t_start = time.perf_counter()

    project_id = _validate_project_id(req.project_id)

    t_retr_start = time.perf_counter()
    if project_id is not None:
        chunks, _truncated = _build_project_context_chunks(req.query, project_id, req.tier)
    else:
        source_paths = _resolve_source_paths(req.source_paths)
        if not source_paths:
            raise HTTPException(
                status_code=400,
                detail="No literature source paths configured",
            )
        chunks, _truncated = _build_context_chunks(req.query, source_paths, req.tier)
    retrieval_time_ms = (time.perf_counter() - t_retr_start) * 1000.0

    candidates = chunks[: max(req.top_k, 1)]
    selected = candidates  # spike: no rerank/budget filter yet

    t_prompt_start = time.perf_counter()
    context_strings = _build_context_strings(selected)
    prompt_full = "\n\n---\n\n".join(context_strings)
    prompt_build_time_ms = (time.perf_counter() - t_prompt_start) * 1000.0

    prompt_preview = _truncate_preview(prompt_full, limit=_PROMPT_PREVIEW_LIMIT)
    prompt_template = (
        prompt_full if req.include_full_prompt and is_dev_mode_enabled() else None
    )

    total_time_ms = (time.perf_counter() - t_start) * 1000.0

    return ChatDebugResponse(
        trace_id=trace_id,
        query=req.query,
        rewritten_query=None,
        retrieval_results=_to_debug_chunks(candidates),
        selected_chunks=_to_debug_chunks(selected),
        rejected_chunks=[],
        prompt_preview=prompt_preview,
        prompt_template=prompt_template,
        answer=None,
        confidence_score=None,
        confidence_label=None,
        metrics=DebugMetrics(
            retrieval_time_ms=retrieval_time_ms,
            prompt_build_time_ms=prompt_build_time_ms,
            total_time_ms=total_time_ms,
        ),
    )
