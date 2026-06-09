"""
Pydantic models for the Literature Evolution Layer.

Source of truth for the candidate record contract.

These models are used by:
  - literature_assistant/core/evolution/store.py (SQLite persistence)
  - literature_assistant/core/evolution/service.py (orchestration)
  - literature_assistant/core/routers/evolution_router.py (FastAPI contracts)

Backend remains authoritative for risk, dedupe, eligibility, and promotion;
the frontend must not be trusted to decide safety.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CandidateSourceType(str, Enum):
    INSPIRATION = "inspiration"
    DISCUSSION = "discussion"
    RAG_ANSWER = "rag_answer"
    RUNTIME_JOB = "runtime_job"
    SKILL_RUN = "skill_run"
    PDF_ANNOTATION = "pdf_annotation"
    MCP_TOOL_USE = "mcp_tool_use"
    MANUAL = "manual"
    CURATOR = "curator"


class CandidateMemoryType(str, Enum):
    USER_PREFERENCE = "user_preference"
    PROJECT_FACT = "project_fact"
    LITERATURE_PROCEDURE = "literature_procedure"
    DOMAIN_KNOWLEDGE = "domain_knowledge"
    EVIDENCE_RULE = "evidence_rule"
    AGENT_ROLE_LESSON = "agent_role_lesson"
    TOOL_RELIABILITY = "tool_reliability"
    SKILL_DRAFT = "skill_draft"


class CandidateStatus(str, Enum):
    CAPTURED = "captured"
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SNOOZED = "snoozed"
    EXPIRED = "expired"
    PROMOTED_TO_MEMORY = "promoted_to_memory"
    PROMOTED_TO_SKILL_DRAFT = "promoted_to_skill_draft"
    ROLLED_BACK = "rolled_back"
    BLOCKED = "blocked"


class CandidateRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExperienceCandidate(BaseModel):
    """A single experience candidate produced by the evolution capture layer.

    Mirrors the experience candidate contract. All fields are validated at
    write time; status transitions are enforced by
    literature_assistant.core.evolution.state_machine.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    user_id: Optional[str] = Field(default=None, max_length=128)
    project_id: Optional[str] = Field(default=None, max_length=128)

    source_type: CandidateSourceType
    source_id: str = Field(min_length=1, max_length=256)
    source_route: Optional[str] = Field(default=None, max_length=512)
    source_summary: str = Field(min_length=1, max_length=2048)

    memory_type: CandidateMemoryType
    title: str = Field(min_length=1, max_length=512)
    claim: str = Field(min_length=1, max_length=4096)
    future_use: str = Field(min_length=1, max_length=2048)

    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list, max_length=64)
    confidence: float = Field(ge=0.0, le=1.0)
    risk_level: CandidateRiskLevel = CandidateRiskLevel.LOW

    status: CandidateStatus = CandidateStatus.CAPTURED
    dedupe_hash: str = Field(min_length=8, max_length=128)
    decision_reason: Optional[str] = Field(default=None, max_length=1024)
    rollback_ref: Optional[str] = Field(default=None, max_length=256)

    created_at: str = Field(min_length=10, max_length=64)
    updated_at: str = Field(min_length=10, max_length=64)
    decided_at: Optional[str] = Field(default=None, max_length=64)
    promoted_at: Optional[str] = Field(default=None, max_length=64)


class EvolutionStatusPayload(BaseModel):
    """Health and configuration snapshot for `/evolution/status`."""

    enabled: bool
    recall_enabled: bool
    candidate_capture_enabled: bool
    review_ui_enabled: bool
    promotion_enabled: bool
    curator_enabled: bool
    db_path: str
    candidate_counts: Dict[str, int] = Field(default_factory=dict)
    reason: Optional[str] = None


class CandidateListPayload(BaseModel):
    """List response for `/evolution/candidates`."""

    items: List[ExperienceCandidate] = Field(default_factory=list)
    total: int = Field(ge=0)


class CandidateDecisionRequest(BaseModel):
    """Body for accept/reject/snooze/rollback transition POSTs."""

    model_config = ConfigDict(extra="forbid")

    decision_reason: Optional[str] = Field(default=None, max_length=1024)
    rollback_ref: Optional[str] = Field(default=None, max_length=256)


class CandidateDecisionPayload(BaseModel):
    """Response shape for transition POSTs."""

    candidate_id: str
    previous_status: CandidateStatus
    new_status: CandidateStatus
    decided_at: str
    decision_reason: Optional[str] = None


class CandidatePromotionPayload(BaseModel):
    """Response shape for `/evolution/candidates/{id}/promote`."""

    candidate_id: str
    previous_status: CandidateStatus
    new_status: CandidateStatus
    promoted: bool
    target: str  # "memory" | "skill_draft" | "none"
    rollback_ref: Optional[str] = None
    reason: str
    promoted_at: Optional[str] = None


class CuratorRunPayload(BaseModel):
    """Response shape for one curator pass."""

    enabled: bool
    workspace_id: Optional[str] = None
    scanned: int = 0
    expired: List[str] = Field(default_factory=list)
    demoted: List[str] = Field(default_factory=list)
    conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    dedupe_groups: List[Dict[str, Any]] = Field(default_factory=list)
    skipped: Dict[str, int] = Field(default_factory=dict)
    reason: Optional[str] = None


class EvolutionAuditPayload(BaseModel):
    """Read-only experience review summary for the audit panel.

    Counts and recent decisions are bounded so the panel can explain review
    activity without exposing full candidate text.
    """

    workspace_id: Optional[str] = None
    total: int = 0
    by_status: Dict[str, int] = Field(default_factory=dict)
    by_memory_type: Dict[str, int] = Field(default_factory=dict)
    by_source_type: Dict[str, int] = Field(default_factory=dict)
    promotion_outcomes: Dict[str, int] = Field(default_factory=dict)
    recent_decisions: List[Dict[str, Any]] = Field(default_factory=list)
