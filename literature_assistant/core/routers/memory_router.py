# -*- coding: utf-8 -*-
"""Memory API Router - Bridge to MemPalace and runtime sync services."""

import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from models import (
    MemoryStatusPayload,
    MemorySearchRequest,
    MemorySearchResponsePayload,
    MemoryWakeupPayload,
    MemorySyncPayload,
)

logger = logging.getLogger("MemoryRouter")
router = APIRouter(prefix="/memory", tags=["Memory"])
compat_router = APIRouter(prefix="/api/memory_palace", tags=["Memory"])


class MemoryCreateRequest(BaseModel):
    """Create request for one repository-owned long-term memory row."""

    content: str = Field(min_length=1, max_length=20000)
    wing: str | None = Field(default=None, max_length=128)
    room: str | None = Field(default=None, max_length=128)
    source_file: str = Field(default="", max_length=512)
    metadata: dict[str, object] = Field(default_factory=dict)
    added_by: str = Field(default="memory-api", max_length=128)


class MemoryRecordPayload(BaseModel):
    """Public long-term memory row returned by CRUD endpoints."""

    memory_id: str
    text: str
    wing: str
    room: str
    source_file: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)


class MemoryCreateResponsePayload(BaseModel):
    """Create response for a memory row."""

    success: bool
    available: bool
    memory_id: str | None = None
    duplicate: bool = False
    wing: str
    room: str
    reason: str | None = None


class MemoryListResponsePayload(BaseModel):
    """Bounded list response for repository-owned memory rows."""

    available: bool
    memories: list[MemoryRecordPayload]


class MemoryDeleteResponsePayload(BaseModel):
    """Delete response for one memory row."""

    deleted: bool
    memory_id: str


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


async def _search_memory_impl(request: MemorySearchRequest) -> MemorySearchResponsePayload:
    """Search MemPalace through the shared adapter."""
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


@router.post("/search", response_model=MemorySearchResponsePayload)
async def search_memory(request: MemorySearchRequest) -> MemorySearchResponsePayload:
    """Search MemPalace for project memory."""
    return await _search_memory_impl(request)


@compat_router.post("/search", response_model=MemorySearchResponsePayload)
async def search_memory_palace(request: MemorySearchRequest) -> MemorySearchResponsePayload:
    """Compatibility alias for matrix-era MemPalace search clients."""
    return await _search_memory_impl(request)


@compat_router.post("/memories", response_model=MemoryCreateResponsePayload)
async def create_memory(request: MemoryCreateRequest) -> MemoryCreateResponsePayload:
    """Create one long-term memory row through the shared MemPalace adapter."""

    adapter = get_memory_adapter()
    if not adapter:
        raise HTTPException(status_code=501, detail="Memory adapter not available")
    try:
        result = adapter.add_memory(
            wing=request.wing or "",
            room=request.room or "",
            content=request.content,
            source_file=request.source_file,
            metadata=request.metadata,
            added_by=request.added_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MemoryCreateResponsePayload(
        success=result.success,
        available=result.available,
        memory_id=result.drawer_id,
        duplicate=result.duplicate,
        wing=result.wing,
        room=result.room,
        reason=result.reason,
    )


@compat_router.get("/memories", response_model=MemoryListResponsePayload)
async def list_memories(
    wing: str | None = Query(default=None),
    room: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> MemoryListResponsePayload:
    """List repository-owned long-term memory rows with optional scope filters."""

    adapter = get_memory_adapter()
    if not adapter:
        raise HTTPException(status_code=501, detail="Memory adapter not available")
    records = adapter.list_memories(wing=wing, room=room, limit=limit)
    return MemoryListResponsePayload(
        available=True,
        memories=[MemoryRecordPayload(**record.to_dict()) for record in records],
    )


@compat_router.get("/memories/{memory_id}", response_model=MemoryRecordPayload)
async def get_memory(memory_id: str) -> MemoryRecordPayload:
    """Return one repository-owned long-term memory row."""

    adapter = get_memory_adapter()
    if not adapter:
        raise HTTPException(status_code=501, detail="Memory adapter not available")
    try:
        record = adapter.get_memory(memory_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"memory not found: {memory_id}")
    return MemoryRecordPayload(**record.to_dict())


@compat_router.delete("/memories/{memory_id}", response_model=MemoryDeleteResponsePayload)
async def delete_memory(memory_id: str) -> MemoryDeleteResponsePayload:
    """Delete one repository-owned long-term memory row."""

    adapter = get_memory_adapter()
    if not adapter:
        raise HTTPException(status_code=501, detail="Memory adapter not available")
    try:
        deleted = adapter.delete_memory(memory_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"memory not found: {memory_id}")
    return MemoryDeleteResponsePayload(deleted=True, memory_id=memory_id)


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
    wing: str | None = Query(None),
    room: str | None = Query(None),
) -> MemorySyncPayload:
    """Synchronize evidence from a completed job into long-term memory."""
    from writing_runtime import get_writing_runtime
    runtime = get_writing_runtime()
    try:
        result = runtime.sync_job_to_memory(job_id, wing=wing, room=room)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MemorySyncPayload(
        success=bool(result.get("success", False)),
        available=bool(result.get("available", False)),
        wing=str(result.get("wing") or wing or ""),
        room=str(result.get("room") or room or ""),
        drawer_id=result.get("drawer_id"),
        duplicate=bool(result.get("duplicate", False)),
        reason=result.get("reason"),
    )
