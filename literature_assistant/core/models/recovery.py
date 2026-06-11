"""
Recovery Console-related Pydantic models for REST API.

Includes models for event timeline, memory snapshots, and recovery operations.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RecoveryActionType(str, Enum):
    """Canonical recovery action types.

    早期 recovery_console / recovery_recommendation_engine 各自定义同名枚举
    导致 router 序列化 ``rec.action_type.value`` 时,客户端拿到的 value 取决
    于哪个 module 创建的实例。这里把两侧并集合并为唯一源,两侧 ``from
    models.recovery import RecoveryActionType``。
    """
    REPLAY_JOB = "replay_job"
    REBUILD_STATE = "rebuild_state"
    RECREATE_WAKEUP = "recreate_wakeup"
    REHYDRATE_RUNTIME = "rehydrate_runtime"
    INVALIDATE_FACT = "invalidate_fact"
    RECOVER_FROM_SNAPSHOT = "recover_from_snapshot"
    INSPECT_EVENTS = "inspect_events"
    INSPECT_MEMORY = "inspect_memory"
    REBUILD_WAKEUP = "rebuild_wakeup"


class RecoveryEventPayload(BaseModel):
    """Single event in recovery timeline."""

    event_id: str
    event_type: str
    timestamp: str
    source_job_id: Optional[str] = None
    source_session_id: Optional[str] = None
    event_data: Dict[str, Any]


class EventTimelinePayload(BaseModel):
    """Event timeline response for recovery inspection."""

    events: List[RecoveryEventPayload]
    event_count: int
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    session_filter: Optional[str] = None
    job_filter: Optional[str] = None


class MemoryFactPayload(BaseModel):
    """Single fact from memory snapshot."""

    fact_id: str
    namespace: str
    subject: str
    predicate: str
    object: str
    object_type: str = "string"
    valid_from: str
    valid_to: Optional[str] = None
    source_event_id: str


class MemorySnapshotPayload(BaseModel):
    """Memory snapshot response for recovery inspection."""

    facts: List[MemoryFactPayload]
    fact_count: int
    namespaces: List[str]
    last_updated: str


class InvalidFactRequest(BaseModel):
    """Request to invalidate fact(s) by ID and namespace."""

    fact_id: str = Field(..., description="Unique ID of the fact to invalidate")
    namespace: str = Field(..., description="Namespace context for the fact")
    reason: Optional[str] = Field(None, description="Optional reason for invalidation")
    invalidated_by: Optional[str] = Field("system", description="Entity performing the invalidation")


class FactInvalidationPayload(BaseModel):
    """Response for fact invalidation operation."""
    
    fact_id: str
    namespace: str
    reason: str
    previous_value: Optional[str] = None
    invalidated_at: str
    invalidated_by: str
    success: bool


class EventFilterPayload(BaseModel):
    """Filter options for event timeline."""

    session_id: Optional[str] = None
    job_id: Optional[str] = None
    event_type: Optional[str] = None
    timestamp_start: Optional[str] = None
    timestamp_end: Optional[str] = None


class TimelineQueryRequest(BaseModel):
    """Request to query event timeline."""

    filters: Optional[EventFilterPayload] = None
    limit: int = 100
    offset: int = 0


class TimelineQueryResponse(BaseModel):
    """Response for event timeline query."""

    events: List[RecoveryEventPayload]
    total_count: int
    limit: int
    offset: int


class RecommendationEvidencePayload(BaseModel):
    """Single piece of evidence supporting a recommendation."""
    
    source_type: str  # "event" | "fact" | "memory" | "pattern"
    source_id: str  # Event/fact/memory record ID
    relevance: float  # 0.0-1.0 relevance score
    description: str  # Human-readable evidence description


class RecoveryRecommendationPayload(BaseModel):
    """Single typed recovery recommendation with evidence tracing."""
    
    recommendation_id: str
    job_id: str
    action_type: str  # RecoveryActionType enum value
    rationale: str
    confidence: float
    priority: int
    approval_level: str  # ApprovalLevel enum value
    dry_run_preview: str
    time_to_remediate_minutes: Optional[int] = None
    risk_level: str  # "low" | "medium" | "high"
    risk_description: str
    reversibility: str  # "fully_reversible" | "partially_reversible" | "irreversible"
    evidence: List[RecommendationEvidencePayload]
    source_event_ids: List[str]
    source_fact_ids: List[str]
    memory_hit_ids: List[str]
    created_at: str


class RecommendationsResponsePayload(BaseModel):
    """Response containing recovery recommendations."""
    
    request_id: str
    generated_at: str
    primary_recommendation: Optional[RecoveryRecommendationPayload] = None
    alternatives: List[RecoveryRecommendationPayload]
    total_evidence_considered: int
    generation_duration_ms: float
