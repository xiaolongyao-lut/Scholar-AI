"""
Memory-related Pydantic models for REST API.

Includes models for MemPalace integration, semantic search, and memory synchronization.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MemoryStatusPayload(BaseModel):
    """MemPalace integration diagnostics."""

    enabled: bool
    available: bool
    vendor_repo_path: str
    palace_path: str
    collection_name: str
    default_wing: str
    default_room: str
    search_limit: int
    max_content_chars: int
    auto_sync_runtime_jobs: bool
    identity_path: Optional[str] = None
    reason: Optional[str] = None


class MemorySearchRequest(BaseModel):
    """Semantic memory search request."""

    query: str
    wing: Optional[str] = None
    room: Optional[str] = None
    limit: Optional[int] = None


class MemorySearchHitPayload(BaseModel):
    """Single MemPalace search hit."""

    text: str
    wing: str
    room: str
    source_file: str
    similarity: float


class MemorySearchResponsePayload(BaseModel):
    """Search response payload for MemPalace queries."""

    query: str
    wing: Optional[str] = None
    room: Optional[str] = None
    available: bool
    reason: Optional[str] = None
    results: List[MemorySearchHitPayload] = Field(default_factory=list)


class MemoryWakeupPayload(BaseModel):
    """Wake-up context payload built from Layer0 + Layer1."""

    wing: Optional[str] = None
    context: str
    token_estimate: int
    available: bool
    reason: Optional[str] = None


class MemorySyncPayload(BaseModel):
    """Result payload for runtime-to-memory synchronization."""

    success: bool
    available: bool
    wing: str
    room: str
    drawer_id: Optional[str] = None
    duplicate: bool = False
    reason: Optional[str] = None
