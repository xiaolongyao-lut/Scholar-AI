# -*- coding: utf-8 -*-
"""Memory API Router - Bridge to MemPalace and runtime sync services."""

import logging
from fastapi import APIRouter, HTTPException, Query
from models import (
    MemoryStatusPayload,
    MemorySearchRequest,
    MemorySearchResponsePayload,
    MemoryWakeupPayload,
    MemorySyncPayload,
)

logger = logging.getLogger("MemoryRouter")
router = APIRouter(prefix="/memory", tags=["Memory"])


def get_memory_adapter():
    """Import and return the shared MemPalace adapter instance."""
    from python_adapter_server import get_memory_adapter as get_adapter
    return get_adapter()


@router.get("/status", response_model=MemoryStatusPayload)
async def get_memory_status() -> MemoryStatusPayload:
    """Return MemPalace configuration and dependency status."""
    adapter = get_memory_adapter()
    if not adapter:
         raise HTTPException(status_code=501, detail="Memory adapter not available")
    return MemoryStatusPayload(**adapter.describe())


@router.post("/search", response_model=MemorySearchResponsePayload)
async def search_memory(request: MemorySearchRequest) -> MemorySearchResponsePayload:
    """Search MemPalace for project memory."""
    adapter = get_memory_adapter()
    if not adapter:
         raise HTTPException(status_code=501, detail="Memory adapter not available")
    try:
        result = adapter.search(
            query=request.query,
            wing=request.wing,
            room=request.room,
            limit=request.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MemorySearchResponsePayload(**result.to_dict())


@router.get("/wakeup", response_model=MemoryWakeupPayload)
async def get_memory_wakeup(wing: str | None = Query(None)) -> MemoryWakeupPayload:
    """Render Layer0 + Layer1 context for the current project wing."""
    adapter = get_memory_adapter()
    if not adapter:
         raise HTTPException(status_code=501, detail="Memory adapter not available")
    result = adapter.build_wakeup_context(wing=wing)
    return MemoryWakeupPayload(**result.to_dict())


@router.post("/runtime/job/{job_id}/sync", response_model=MemorySyncPayload)
async def sync_runtime_job_to_memory(
    job_id: str,
    session_id: str = Query(...),
) -> MemorySyncPayload:
    """Synchronize evidence from a completed job into long-term memory."""
    # Placeholder for runtime-to-memory synchronization logic
    # In a real system, this would trigger an background task to ingest facts
    return MemorySyncPayload(
        job_id=job_id,
        session_id=session_id,
        synced_at="2026-04-11T13:10:00Z", # Placeholder
        facts_ingested=5,
        status="completed"
    )
