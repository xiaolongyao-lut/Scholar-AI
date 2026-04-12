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


class CreateSessionRequest(BaseModel):
    """Request to create a writing session."""

    mode: str  # "prompt", "skill", "hybrid"
    user_id: Optional[str] = None
    settings: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


class SessionPayload(BaseModel):
    """Writing session response."""

    session_id: str
    user_id: Optional[str]
    mode: str
    created_at: str
    settings: Dict[str, Any]
    tags: List[str]


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


class EventPayload(BaseModel):
    """Event response payload."""

    event_id: str
    job_id: str
    session_id: str
    event_type: str
    timestamp: str
    data: Dict[str, Any]


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
