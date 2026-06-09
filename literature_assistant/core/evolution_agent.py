"""Compatibility facade for Evolution candidate generation.

The active implementation lives in ``evolution.service`` plus source-specific
capture extractors. This module preserves the historical ``evolution_agent.py``
entrypoint name for matrix-era callers without bypassing secret scanning,
dedupe, or state-machine rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evolution.service import EvolutionService, get_evolution_service
from evolution.store import StoreWriteResult
from models.evolution import (
    CandidateMemoryType,
    CandidateRiskLevel,
    CandidateSourceType,
    ExperienceCandidate,
)


@dataclass(frozen=True, slots=True)
class EvolutionCandidateInput:
    """Input shape for one manually generated evolution candidate.

    Args:
        workspace_id: Non-empty workspace identifier.
        source_type: Origin surface for the candidate.
        source_id: Stable source identifier from the origin surface.
        source_summary: Short source summary safe for reviewer display.
        memory_type: Target memory/category for promotion.
        title: Reviewer-facing candidate title.
        claim: Candidate claim to store and deduplicate.
        future_use: How the candidate should be reused if accepted.
        confidence: Score in the inclusive [0, 1] range.
    """

    workspace_id: str
    source_type: CandidateSourceType
    source_id: str
    source_summary: str
    memory_type: CandidateMemoryType
    title: str
    claim: str
    future_use: str
    confidence: float
    user_id: str | None = None
    project_id: str | None = None
    source_route: str | None = None
    evidence_refs: list[dict[str, Any]] | None = None
    risk_level: CandidateRiskLevel = CandidateRiskLevel.LOW


class EvolutionAgent:
    """Stable F2 facade over ``EvolutionService.capture``."""

    def __init__(self, service: EvolutionService | None = None) -> None:
        self._service = service or get_evolution_service()

    def generate_candidate(self, candidate_input: EvolutionCandidateInput) -> StoreWriteResult:
        """Generate one candidate through the authoritative service path."""
        if not isinstance(candidate_input, EvolutionCandidateInput):
            raise TypeError("candidate_input must be EvolutionCandidateInput")
        self._validate_input(candidate_input)
        return self._service.capture(
            workspace_id=candidate_input.workspace_id.strip(),
            source_type=candidate_input.source_type,
            source_id=candidate_input.source_id.strip(),
            source_summary=candidate_input.source_summary.strip(),
            memory_type=candidate_input.memory_type,
            title=candidate_input.title.strip(),
            claim=candidate_input.claim.strip(),
            future_use=candidate_input.future_use.strip(),
            confidence=float(candidate_input.confidence),
            user_id=candidate_input.user_id,
            project_id=candidate_input.project_id,
            source_route=candidate_input.source_route,
            evidence_refs=candidate_input.evidence_refs,
            risk_level=candidate_input.risk_level,
        )

    def list_candidates(
        self,
        *,
        workspace_id: str | None = None,
        sort_by: str = "updated_at",
        limit: int = 50,
    ) -> list[ExperienceCandidate]:
        """List candidates through the authoritative service path."""
        if limit < 1:
            raise ValueError("limit must be positive")
        return self._service.list(workspace_id=workspace_id, sort_by=sort_by, limit=limit)

    @staticmethod
    def _validate_input(candidate_input: EvolutionCandidateInput) -> None:
        required = {
            "workspace_id": candidate_input.workspace_id,
            "source_id": candidate_input.source_id,
            "source_summary": candidate_input.source_summary,
            "title": candidate_input.title,
            "claim": candidate_input.claim,
            "future_use": candidate_input.future_use,
        }
        missing = [name for name, value in required.items() if not isinstance(value, str) or not value.strip()]
        if missing:
            raise ValueError(f"candidate input has empty fields: {', '.join(missing)}")
        if not 0.0 <= float(candidate_input.confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


def build_evolution_agent(service: EvolutionService | None = None) -> EvolutionAgent:
    """Return the stable F2 entrypoint for candidate generation."""
    return EvolutionAgent(service=service)
