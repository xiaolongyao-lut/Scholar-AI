"""Experience review API router.

Endpoints take ``EvolutionService`` via FastAPI dependencies so tests can use
isolated stores while the application keeps a shared default service.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from evolution import EvolutionService, get_evolution_service
from evolution.config import (
    is_candidate_capture_enabled,
    is_promotion_enabled,
    is_review_ui_enabled,
    load_evolution_config,
)
from evolution.store import default_db_path
from models.evolution import (
    CandidateDecisionPayload,
    CandidateDecisionRequest,
    CandidateListPayload,
    CandidateMemoryType,
    CandidatePromotionPayload,
    CandidateRiskLevel,
    CandidateSourceType,
    CandidateStatus,
    CuratorRunPayload,
    EvolutionAuditPayload,
    EvolutionStatusPayload,
    ExperienceCandidate,
)

logger = logging.getLogger("EvolutionRouter")
router = APIRouter(prefix="/evolution", tags=["Evolution"])


def _candidate_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail="经验候选不存在或已被删除。",
    )


# --- status ------------------------------------------------------------------

@router.get("/status", response_model=EvolutionStatusPayload)
async def get_evolution_status(
    service: EvolutionService = Depends(get_evolution_service),
) -> EvolutionStatusPayload:
    """Return the local experience-review feature state and item counts."""

    cfg = load_evolution_config()
    counts = service.status_counts()
    return EvolutionStatusPayload(
        enabled=True,
        recall_enabled=bool(cfg.get("recall_enabled", False)),
        candidate_capture_enabled=is_candidate_capture_enabled(),
        review_ui_enabled=is_review_ui_enabled(),
        promotion_enabled=is_promotion_enabled(),
        curator_enabled=bool(cfg.get("curator_enabled", False)),
        db_path=str(default_db_path()),
        candidate_counts=counts,
    )


# --- list --------------------------------------------------------------------

@router.get("/candidates", response_model=CandidateListPayload)
async def list_candidates(
    workspace_id: Optional[str] = Query(None),
    project_id: Optional[str] = Query(None),
    status: Optional[CandidateStatus] = Query(None),
    memory_type: Optional[CandidateMemoryType] = Query(None),
    sort_by: Literal["updated_at", "created_at", "confidence"] = Query("updated_at"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: EvolutionService = Depends(get_evolution_service),
) -> CandidateListPayload:
    """List reviewable experience items with optional filters."""

    memory_type_value = memory_type.value if memory_type else None
    items = service.list(
        workspace_id=workspace_id,
        project_id=project_id,
        status=status,
        memory_type=memory_type_value,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )
    total = service.count(
        workspace_id=workspace_id,
        project_id=project_id,
        status=status,
        memory_type=memory_type_value,
    )
    return CandidateListPayload(items=items, total=total)


# --- transitions -------------------------------------------------------------

def _apply_transition(
    service: EvolutionService,
    candidate_id: str,
    action: str,
    request: CandidateDecisionRequest,
) -> CandidateDecisionPayload:
    existing = service.get(candidate_id)
    if existing is None:
        raise _candidate_not_found_error()
    previous_status = existing.status

    try:
        if action == "accept":
            result = service.accept(candidate_id, decision_reason=request.decision_reason)
        elif action == "reject":
            result = service.reject(candidate_id, decision_reason=request.decision_reason)
        elif action == "snooze":
            result = service.snooze(candidate_id, decision_reason=request.decision_reason)
        elif action == "rollback":
            result = service.rollback(
                candidate_id,
                rollback_ref=request.rollback_ref,
                decision_reason=request.decision_reason,
            )
        else:  # pragma: no cover
            raise HTTPException(status_code=400, detail="不支持的经验候选操作。")
    except KeyError as exc:
        raise _candidate_not_found_error() from exc

    if not result.transition_applied:
        raise HTTPException(status_code=409, detail=result.reason)

    return CandidateDecisionPayload(
        candidate_id=result.candidate.candidate_id,
        previous_status=previous_status,
        new_status=result.candidate.status,
        decided_at=result.candidate.decided_at or result.candidate.updated_at,
        decision_reason=result.candidate.decision_reason,
    )


@router.post("/candidates/{candidate_id}/accept", response_model=CandidateDecisionPayload)
async def accept_candidate(
    candidate_id: str,
    request: CandidateDecisionRequest = CandidateDecisionRequest(),
    service: EvolutionService = Depends(get_evolution_service),
) -> CandidateDecisionPayload:
    return _apply_transition(service, candidate_id, "accept", request)


@router.post("/candidates/{candidate_id}/reject", response_model=CandidateDecisionPayload)
async def reject_candidate(
    candidate_id: str,
    request: CandidateDecisionRequest = CandidateDecisionRequest(),
    service: EvolutionService = Depends(get_evolution_service),
) -> CandidateDecisionPayload:
    return _apply_transition(service, candidate_id, "reject", request)


@router.post("/candidates/{candidate_id}/snooze", response_model=CandidateDecisionPayload)
async def snooze_candidate(
    candidate_id: str,
    request: CandidateDecisionRequest = CandidateDecisionRequest(),
    service: EvolutionService = Depends(get_evolution_service),
) -> CandidateDecisionPayload:
    return _apply_transition(service, candidate_id, "snooze", request)


@router.post("/candidates/{candidate_id}/rollback", response_model=CandidateDecisionPayload)
async def rollback_candidate(
    candidate_id: str,
    request: CandidateDecisionRequest = CandidateDecisionRequest(),
    service: EvolutionService = Depends(get_evolution_service),
) -> CandidateDecisionPayload:
    return _apply_transition(service, candidate_id, "rollback", request)


@router.post("/candidates/{candidate_id}/promote", response_model=CandidatePromotionPayload)
async def promote_candidate(
    candidate_id: str,
    service: EvolutionService = Depends(get_evolution_service),
) -> CandidatePromotionPayload:
    """Apply a saved experience to long-term memory or a workflow draft.

    The item remains unchanged when it cannot be applied.
    """

    try:
        outcome = service.promote(candidate_id)
    except KeyError as exc:
        raise _candidate_not_found_error() from exc

    if outcome.candidate is None:  # pragma: no cover
        raise _candidate_not_found_error()

    if not outcome.promoted:
        raise HTTPException(status_code=409, detail=outcome.reason)

    previous_status = (
        CandidateStatus.ACCEPTED
        if outcome.transition_applied
        else outcome.candidate.status
    )

    return CandidatePromotionPayload(
        candidate_id=outcome.candidate.candidate_id,
        previous_status=previous_status,
        new_status=outcome.candidate.status,
        promoted=outcome.promoted,
        target=outcome.target,
        rollback_ref=outcome.rollback_ref,
        reason=outcome.reason,
        promoted_at=outcome.candidate.promoted_at,
    )


@router.post("/curate/run", response_model=CuratorRunPayload)
async def run_curator(
    workspace_id: Optional[str] = Query(None),
    service: EvolutionService = Depends(get_evolution_service),
) -> CuratorRunPayload:
    """Run one local organizer pass over pending experience items."""

    from evolution import EvolutionCurator, is_curator_enabled

    if not is_curator_enabled():
        return CuratorRunPayload(
            enabled=False,
            workspace_id=workspace_id,
            reason="经验整理功能尚未开启：curator_enabled=false (kill switch)。",
        )

    curator = EvolutionCurator(service)
    result = curator.run(workspace_id=workspace_id)
    return CuratorRunPayload(
        enabled=True,
        workspace_id=workspace_id,
        scanned=result.scanned_count,
        expired=result.expired,
        demoted=result.demoted,
        conflicts=result.conflicts,
        dedupe_groups=result.dedupe_groups,
        skipped=result.skipped,
    )


# --- audit (read-only roll-up) -----------------------------------------------

@router.get("/audit", response_model=EvolutionAuditPayload)
async def get_evolution_audit(
    workspace_id: Optional[str] = Query(None),
    recent_decision_limit: int = Query(10, ge=0, le=50),
    service: EvolutionService = Depends(get_evolution_service),
) -> EvolutionAuditPayload:
    """Return a read-only summary for the experience review panel."""

    summary = service.audit_summary(
        workspace_id=workspace_id,
        recent_decision_limit=recent_decision_limit,
    )
    return EvolutionAuditPayload(**summary)


# --- manual capture ----------------------------------------------------------

class ManualCaptureRequest(BaseModel):
    """Request body for controlled manual experience import."""

    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=256)
    source_summary: str = Field(min_length=1, max_length=2048)
    memory_type: CandidateMemoryType
    title: str = Field(min_length=1, max_length=512)
    claim: str = Field(min_length=1, max_length=4096)
    future_use: str = Field(min_length=1, max_length=2048)
    confidence: float = Field(ge=0.0, le=1.0)
    user_id: Optional[str] = Field(default=None, max_length=128)
    project_id: Optional[str] = Field(default=None, max_length=128)
    source_route: Optional[str] = Field(default=None, max_length=512)
    risk_level: CandidateRiskLevel = CandidateRiskLevel.LOW


class ManualCaptureResponse(BaseModel):
    candidate: ExperienceCandidate
    created: bool
    merged: bool
    reason: str


@router.post("/capture/manual", response_model=ManualCaptureResponse)
async def capture_manual(
    request: ManualCaptureRequest,
    service: EvolutionService = Depends(get_evolution_service),
) -> ManualCaptureResponse:
    """Capture an experience item from a controlled manual source."""

    result = service.capture(
        workspace_id=request.workspace_id,
        source_type=CandidateSourceType.MANUAL,
        source_id=request.source_id,
        source_summary=request.source_summary,
        memory_type=request.memory_type,
        title=request.title,
        claim=request.claim,
        future_use=request.future_use,
        confidence=request.confidence,
        user_id=request.user_id,
        project_id=request.project_id,
        source_route=request.source_route,
        risk_level=request.risk_level,
    )
    return ManualCaptureResponse(
        candidate=result.candidate,
        created=result.created,
        merged=result.merged,
        reason=result.reason,
    )
