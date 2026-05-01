# -*- coding: utf-8 -*-
"""Common API models — shared response envelopes, pagination, error structures.

Patterns learned from:
- openhanako: AppError with code/severity/category/retryable
- open-webui: ERROR_MESSAGES enum, standardized HTTPException
- textgen: Custom exception handlers with code+message
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Standardized Error Response
# ---------------------------------------------------------------------------

class ErrorCode(str, Enum):
    """Machine-readable error codes for client-side branching."""

    # General
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    BAD_REQUEST = "BAD_REQUEST"

    # LLM / Chat
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_AUTH_FAILED = "LLM_AUTH_FAILED"
    LLM_CONNECTION_ERROR = "LLM_CONNECTION_ERROR"
    LLM_RESPONSE_INVALID = "LLM_RESPONSE_INVALID"
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"

    # Resource
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    SECTION_NOT_FOUND = "SECTION_NOT_FOUND"
    DRAFT_NOT_FOUND = "DRAFT_NOT_FOUND"
    MATERIAL_NOT_FOUND = "MATERIAL_NOT_FOUND"
    DUPLICATE_RESOURCE = "DUPLICATE_RESOURCE"

    # Pipeline
    PIPELINE_UNAVAILABLE = "PIPELINE_UNAVAILABLE"
    PIPELINE_FAILED = "PIPELINE_FAILED"

    # Runtime
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"

    # File / Upload
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    FILE_TYPE_UNSUPPORTED = "FILE_TYPE_UNSUPPORTED"
    FILE_UPLOAD_FAILED = "FILE_UPLOAD_FAILED"


class ErrorDetail(BaseModel):
    """Standardized error detail returned in all error responses."""

    code: str = Field(..., description="机器可读错误码")
    message: str = Field(..., description="人类可读错误描述")
    field: Optional[str] = Field(None, description="出错字段（验证错误时）")
    trace_id: Optional[str] = Field(None, description="链路追踪 ID")


class ErrorResponse(BaseModel):
    """Unified error response envelope."""

    ok: bool = False
    error: ErrorDetail


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class PaginationMeta(BaseModel):
    """Pagination metadata included in paginated responses."""

    page: int = Field(..., ge=1, description="当前页码")
    page_size: int = Field(..., ge=1, le=100, description="每页条数")
    total: int = Field(..., ge=0, description="总数")
    total_pages: int = Field(..., ge=0, description="总页数")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response envelope."""

    ok: bool = True
    items: List[T]
    pagination: PaginationMeta


def paginate(items: list, page: int = 1, page_size: int = 20) -> tuple[list, PaginationMeta]:
    """Slice a list and return (page_items, meta)."""
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    total = len(items)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end], PaginationMeta(
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


# ---------------------------------------------------------------------------
# Success Envelope
# ---------------------------------------------------------------------------

class SuccessResponse(BaseModel, Generic[T]):
    """Generic success response envelope."""

    ok: bool = True
    data: T


class MessageResponse(BaseModel):
    """Simple success/status message."""

    ok: bool = True
    message: str


# ---------------------------------------------------------------------------
# Chat Streaming (SSE) models
# ---------------------------------------------------------------------------

class ChatStreamEvent(str, Enum):
    """Server-Sent Event types for streaming chat."""

    TEXT_DELTA = "text_delta"
    THINKING_START = "thinking_start"
    THINKING_DELTA = "thinking_delta"
    THINKING_END = "thinking_end"
    ERROR = "error"
    DONE = "done"
    USAGE = "usage"


class ChatStreamDelta(BaseModel):
    """Single SSE event payload for streaming chat."""

    event: ChatStreamEvent
    delta: Optional[str] = None
    usage: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    model: Optional[str] = None
