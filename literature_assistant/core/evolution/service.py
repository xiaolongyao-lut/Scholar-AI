"""
High-level orchestration for the evolution candidate layer.

Wires store + secret scan + state machine into a small API that routers and
in-process callers can use without touching SQLite directly.

Backend remains authoritative for risk, dedupe, eligibility, and promotion
(plan §Backend Reliability). Secret scan and dedupe gates fire before any row
write; status transitions are validated by state_machine.evaluate_transition.

Promotion to MemPalace and skill drafts is the responsibility of plan §Slice 6
and is intentionally out of scope for Slice 2; this service exposes only the
candidate-store-level state transitions (accept / reject / snooze / rollback).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from models.evolution import (
    CandidateMemoryType,
    CandidateRiskLevel,
    CandidateSourceType,
    CandidateStatus,
    ExperienceCandidate,
)
from evolution.config import is_recall_enabled, load_evolution_config
from evolution.promotion import EvolutionPromoter, PromotionResult
from evolution.secret_scan import scan_candidate_fields
from evolution.store import EvolutionCandidateStore, StoreWriteResult


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class PromotionOutcome:
    """Service-layer wrapper around EvolutionPromoter.PromotionResult.

    Carries the (possibly updated) candidate row alongside the promotion
    decision so callers can return both with a single tuple unpacking.
    `transition_applied=True` iff the candidate row's status actually
    moved this call (False on no-op / forbidden / promoter-rejected paths).
    """

    candidate: Optional[ExperienceCandidate]
    promoted: bool
    target: str  # "memory" | "skill_draft" | "none"
    rollback_ref: Optional[str]
    reason: str
    transition_applied: bool


def compute_dedupe_hash(
    *,
    workspace_id: str,
    project_id: Optional[str],
    memory_type: CandidateMemoryType,
    claim: str,
) -> str:
    """Stable hash for dedupe identity.

    Hash inputs: (workspace_id, project_id or "", memory_type, normalized claim).
    Normalization: lowercase + strip + collapse internal whitespace.
    """

    normalized_claim = " ".join(claim.lower().split())
    payload = "|".join([
        workspace_id,
        project_id or "",
        memory_type.value,
        normalized_claim,
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class EvolutionService:
    """Facade over EvolutionCandidateStore with secret-scan and time stamping."""

    def __init__(
        self,
        store: Optional[EvolutionCandidateStore] = None,
        *,
        promoter: Optional[EvolutionPromoter] = None,
    ) -> None:
        self.store = store or EvolutionCandidateStore()
        self._promoter = promoter
        self._promoter_resolved = promoter is not None

    def capture(
        self,
        *,
        workspace_id: str,
        source_type: CandidateSourceType,
        source_id: str,
        source_summary: str,
        memory_type: CandidateMemoryType,
        title: str,
        claim: str,
        future_use: str,
        confidence: float,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        source_route: Optional[str] = None,
        evidence_refs: Optional[List[Dict[str, Any]]] = None,
        risk_level: CandidateRiskLevel = CandidateRiskLevel.LOW,
    ) -> StoreWriteResult:
        """Create a new candidate (or merge with an existing dedupe peer).

        Secret-scan fires before any write. Findings force status = BLOCKED
        and surface the reason via decision_reason; the row is still persisted
        so reviewers can see why it was blocked.

        S8.1 hotfix (review-queue input contract): non-blocked candidates land
        directly in PENDING so the /evolution/candidates?status=pending inbox
        is immediately useful for the S5 review UI. CAPTURED remains a valid
        state in the state machine for internal-only / backfill flows.
        """

        now = _utc_now_iso()
        dedupe_hash = compute_dedupe_hash(
            workspace_id=workspace_id,
            project_id=project_id,
            memory_type=memory_type,
            claim=claim,
        )
        verdict = scan_candidate_fields(
            title=title,
            claim=claim,
            future_use=future_use,
            source_summary=source_summary,
        )

        if verdict.blocked:
            status = CandidateStatus.BLOCKED
            decision_reason: Optional[str] = verdict.reason
            decided_at: Optional[str] = now
        else:
            status = CandidateStatus.PENDING
            decision_reason = "auto-enqueued: secret_scan clean"
            decided_at = now

        candidate = ExperienceCandidate(
            candidate_id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            user_id=user_id,
            project_id=project_id,
            source_type=source_type,
            source_id=source_id,
            source_route=source_route,
            source_summary=source_summary,
            memory_type=memory_type,
            title=title,
            claim=claim,
            future_use=future_use,
            evidence_refs=evidence_refs or [],
            confidence=confidence,
            risk_level=risk_level,
            status=status,
            dedupe_hash=dedupe_hash,
            decision_reason=decision_reason,
            rollback_ref=None,
            created_at=now,
            updated_at=now,
            decided_at=decided_at,
            promoted_at=None,
        )

        return self.store.insert_or_merge(candidate)

    def mark_pending(self, candidate_id: str) -> StoreWriteResult:
        """Promote a captured candidate to pending (ready for review)."""

        return self.store.transition(
            candidate_id,
            CandidateStatus.PENDING,
            decided_at=_utc_now_iso(),
        )

    def accept(
        self,
        candidate_id: str,
        *,
        decision_reason: Optional[str] = None,
    ) -> StoreWriteResult:
        return self.store.transition(
            candidate_id,
            CandidateStatus.ACCEPTED,
            decided_at=_utc_now_iso(),
            decision_reason=decision_reason,
        )

    def reject(
        self,
        candidate_id: str,
        *,
        decision_reason: Optional[str] = None,
    ) -> StoreWriteResult:
        return self.store.transition(
            candidate_id,
            CandidateStatus.REJECTED,
            decided_at=_utc_now_iso(),
            decision_reason=decision_reason,
        )

    def snooze(
        self,
        candidate_id: str,
        *,
        decision_reason: Optional[str] = None,
    ) -> StoreWriteResult:
        return self.store.transition(
            candidate_id,
            CandidateStatus.SNOOZED,
            decided_at=_utc_now_iso(),
            decision_reason=decision_reason,
        )

    def rollback(
        self,
        candidate_id: str,
        *,
        rollback_ref: Optional[str] = None,
        decision_reason: Optional[str] = None,
    ) -> StoreWriteResult:
        """Mark a promoted candidate as rolled back (tombstone-first per D-EVO-P0-6)."""

        return self.store.transition(
            candidate_id,
            CandidateStatus.ROLLED_BACK,
            decided_at=_utc_now_iso(),
            decision_reason=decision_reason,
            rollback_ref=rollback_ref,
        )

    def promote(self, candidate_id: str) -> "PromotionOutcome":
        """Promote an ACCEPTED candidate to MemPalace memory or skill draft.

        Slice 6 contract (plan §Slice 6 + §D-EVO-P0-6 + §D-EVO-P0-8):
          - candidate must be in ACCEPTED status; otherwise PromotionOutcome
            reports promoted=False and the row is untouched
          - memory_type=SKILL_DRAFT routes to skill-draft proposal path
            (records intent; managed skill manifest creation deferred to
            Slice 6.5)
          - everything else routes to MemPalace add_memory(); on success
            the candidate transitions to PROMOTED_TO_MEMORY with the
            drawer_id stored as rollback_ref
          - kill switch `evolution.promotion_enabled` (default false) short-
            circuits the whole call; row stays ACCEPTED
          - re-promoting an already-PROMOTED candidate returns the existing
            rollback_ref without writing again (idempotent)
        """

        cfg = load_evolution_config()
        if not bool(cfg.get("promotion_enabled", False)):
            existing = self.store.get(candidate_id)
            return PromotionOutcome(
                candidate=existing,
                promoted=False,
                target="none",
                rollback_ref=None,
                reason="evolution.promotion_enabled=false (kill switch)",
                transition_applied=False,
            )

        existing = self.store.get(candidate_id)
        if existing is None:
            raise KeyError(f"candidate not found: {candidate_id}")

        # Idempotent: already promoted → return the stored rollback_ref
        if existing.status in (
            CandidateStatus.PROMOTED_TO_MEMORY,
            CandidateStatus.PROMOTED_TO_SKILL_DRAFT,
        ):
            return PromotionOutcome(
                candidate=existing,
                promoted=True,
                target="memory" if existing.status == CandidateStatus.PROMOTED_TO_MEMORY else "skill_draft",
                rollback_ref=existing.rollback_ref,
                reason=f"already in {existing.status.value} (no-op)",
                transition_applied=False,
            )

        if existing.status != CandidateStatus.ACCEPTED:
            return PromotionOutcome(
                candidate=existing,
                promoted=False,
                target="none",
                rollback_ref=None,
                reason=f"candidate must be ACCEPTED to promote; current={existing.status.value}",
                transition_applied=False,
            )

        promoter = self._get_or_create_promoter()
        promotion = promoter.promote(existing)
        if not promotion.promoted:
            return PromotionOutcome(
                candidate=existing,
                promoted=False,
                target=promotion.target,
                rollback_ref=None,
                reason=promotion.reason,
                transition_applied=False,
            )

        target_status = (
            CandidateStatus.PROMOTED_TO_SKILL_DRAFT
            if promotion.target == "skill_draft"
            else CandidateStatus.PROMOTED_TO_MEMORY
        )
        now = _utc_now_iso()
        transition_result = self.store.transition(
            candidate_id,
            target_status,
            decided_at=now,
            decision_reason=f"promoted: {promotion.reason}",
            rollback_ref=promotion.rollback_ref,
            promoted_at=now,
        )

        return PromotionOutcome(
            candidate=transition_result.candidate,
            promoted=transition_result.transition_applied,
            target=promotion.target,
            rollback_ref=transition_result.candidate.rollback_ref,
            reason=transition_result.reason if not transition_result.transition_applied else promotion.reason,
            transition_applied=transition_result.transition_applied,
        )

    def _get_or_create_promoter(self) -> EvolutionPromoter:
        if self._promoter is not None:
            return self._promoter
        if self._promoter_resolved:
            # Sentinel: caller passed None deliberately; do not auto-create
            return EvolutionPromoter(memory_adapter=None)
        # Lazy resolve shared MemPalace adapter
        try:
            from python_adapter_server import get_memory_adapter
            adapter = get_memory_adapter()
        except Exception:
            adapter = None
        # Lazy resolve shared WritingSkillService for Slice 6.5 managed-skill
        # promotion path. Failures degrade silently to the pre-6.5 proposal-only
        # fallback so the rest of promotion still works in minimal envs / tests.
        try:
            from skills.service import get_writing_skill_service
            skill_service = get_writing_skill_service()
        except Exception:
            skill_service = None
        self._promoter = EvolutionPromoter(
            memory_adapter=adapter,
            skill_service=skill_service,
        )
        self._promoter_resolved = True
        return self._promoter

    def get(self, candidate_id: str) -> Optional[ExperienceCandidate]:
        return self.store.get(candidate_id)

    def list(
        self,
        *,
        workspace_id: Optional[str] = None,
        project_id: Optional[str] = None,
        status: Optional[CandidateStatus] = None,
        memory_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ExperienceCandidate]:
        return self.store.list(
            workspace_id=workspace_id,
            project_id=project_id,
            status=status,
            memory_type=memory_type,
            limit=limit,
            offset=offset,
        )

    def count(
        self,
        *,
        workspace_id: Optional[str] = None,
        project_id: Optional[str] = None,
        status: Optional[CandidateStatus] = None,
        memory_type: Optional[str] = None,
    ) -> int:
        """Pagination-independent count for the same filter set as :meth:`list`."""

        return self.store.count(
            workspace_id=workspace_id,
            project_id=project_id,
            status=status,
            memory_type=memory_type,
        )

    def status_counts(self, *, workspace_id: Optional[str] = None) -> Dict[str, int]:
        return self.store.count_by_status(workspace_id=workspace_id)

    def audit_summary(
        self,
        *,
        workspace_id: Optional[str] = None,
        recent_decision_limit: int = 10,
    ) -> Dict[str, Any]:
        """Opt §6: read-only roll-up for /evolution/audit."""

        return self.store.audit_summary(
            workspace_id=workspace_id,
            recent_decision_limit=recent_decision_limit,
        )


_service_singleton: Optional[EvolutionService] = None


def get_evolution_service() -> EvolutionService:
    """Process-wide singleton — created lazily on first call.

    Used both as a plain function (capture sites, scripts) and as a
    FastAPI dependency (router endpoints via `Depends`). Tests should
    prefer `app.dependency_overrides[get_evolution_service] = lambda: ...`
    over `reset_evolution_service_for_tests` so per-test isolation does
    not leak through the singleton between tests.
    """

    global _service_singleton
    if _service_singleton is None:
        _service_singleton = EvolutionService()
    return _service_singleton


def reset_evolution_service_for_tests(service: Optional[EvolutionService] = None) -> None:
    """Reset singleton (test-only hook; safe to call from any thread).

    Retained for backwards compatibility — capture sites still use the
    singleton, so tests that exercise both router and capture paths
    benefit from setting both. New router-only tests should use
    `app.dependency_overrides[get_evolution_service]` instead.
    """

    global _service_singleton
    _service_singleton = service
