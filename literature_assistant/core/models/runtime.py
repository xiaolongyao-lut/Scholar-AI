"""
Runtime-related Pydantic models for REST API.

Includes models for writing sessions, jobs, events, and artifacts.
"""

from typing import Any, Dict, List, Optional
from enum import Enum
from pydantic import BaseModel, Field


class TaskState(str, Enum):
    """Lifecycle state for background pipeline tasks."""

    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class CreateSessionRequest(BaseModel):
    """Request to create a writing session."""

    mode: str  # "prompt", "skill", "hybrid"
    user_id: Optional[str] = None
    settings: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    workspace_root: Optional[str] = None
    entry_cwd: Optional[str] = None
    title: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionPayload(BaseModel):
    """Writing session response."""

    session_id: str
    user_id: Optional[str]
    mode: str
    created_at: str
    settings: Dict[str, Any]
    tags: List[str]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CreateJobRequest(BaseModel):
    """Request to create a job in a session."""

    session_id: str
    kind: str  # "prompt_action", "skill_action", "pipeline_run", etc.
    input_text: str = ""
    action_id: Optional[str] = None
    skill_id: Optional[str] = None
    scope: Optional[str] = None
    output_mode: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class JobPayload(BaseModel):
    """Job response payload."""

    job_id: str
    session_id: str
    kind: str
    status: str
    input_text: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    action_id: Optional[str] = None
    skill_id: Optional[str] = None
    error: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class JobStatusPayload(BaseModel):
    """Detailed job status response."""

    job_id: str
    session_id: str
    status: str
    kind: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    is_paused: bool
    is_cancelled: bool
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventPayload(BaseModel):
    """Event response payload."""

    event_id: str
    job_id: str
    session_id: str
    event_type: str
    timestamp: str
    sequence: int = Field(ge=0)
    data: Dict[str, Any]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class JobEventSnapshotPayload(BaseModel):
    """Refresh-safe job snapshot plus cursor-paginated event page."""

    job_id: str
    session_id: str
    job: JobPayload
    status: JobStatusPayload
    events: List[EventPayload] = Field(default_factory=list)
    next_after_sequence: Optional[int] = None
    latest_sequence: int = Field(ge=0)
    has_more: bool = False


class ArtifactPayload(BaseModel):
    """Artifact response payload."""

    artifact_id: str
    job_id: str
    session_id: str
    artifact_type: str
    content: str | Dict[str, Any]
    created_at: str
    created_by: Optional[str] = None
    mime_type: str = "application/json"


class TimelineItemPayload(BaseModel):
    """Append-only transcript event payload."""

    event_id: str
    session_id: str
    event_kind: str
    timestamp: str
    workspace_key: str
    payload: Dict[str, Any]
    parent_event_id: Optional[str] = None


class TimelinePagePayload(BaseModel):
    """Cursor-paginated transcript page."""

    session_id: str
    head_event_id: Optional[str] = None
    items: List[TimelineItemPayload] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class CheckpointPayload(BaseModel):
    """Checkpoint summary payload."""

    checkpoint_id: str
    session_id: str
    event_id: str
    created_at: str
    kind: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    active: bool = False


class ResumeSessionPayload(BaseModel):
    """Session resume response payload."""

    session: SessionPayload
    head_event_id: Optional[str] = None
    head_checkpoint_id: Optional[str] = None
    timeline: List[TimelineItemPayload] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class RewindSessionRequest(BaseModel):
    """Request to rewind a session to a checkpoint."""

    checkpoint_id: str
    mode: str = "conversation_only"


class ForkSessionRequest(BaseModel):
    """Request to fork a session from a checkpoint."""

    checkpoint_id: str
    title: Optional[str] = None


class SkillRunResultPayload(BaseModel):
    """Transform result payload returned to the frontend."""

    jobId: str
    actionId: str
    skillId: str
    inputText: str
    outputText: str
    scope: str
    outputMode: str
    createdAt: str
    applied: bool
