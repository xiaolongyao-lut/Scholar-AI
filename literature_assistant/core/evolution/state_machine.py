"""
Pure-function state machine for ExperienceCandidate transitions.

Source: docs/plans/active/2026-05-17-literature-evolution-agent-incremental-upgrade-plan.md
        §Locked P0 Decisions D-EVO-P0-8 (idempotency) + §Implementation Slices Slice 2.

Allowed transitions (S = source, T = target):
    captured       -> pending | blocked
    pending        -> accepted | rejected | snoozed | expired | blocked
    accepted       -> promoted_to_memory | promoted_to_skill_draft | rolled_back
    snoozed        -> pending | expired
    promoted_*     -> rolled_back
    rolled_back    -> (terminal)
    rejected       -> (terminal)
    expired        -> (terminal)
    blocked        -> (terminal — manual unblock requires a fresh candidate)

Forbidden per D-EVO-P0-8:
    - reject-after-promote
    - re-accept-after-rollback
    - any transition from a terminal state to a non-terminal state

Idempotency:
    - Self-transitions (X -> X) are explicitly idempotent and report no_op=True;
      callers must treat them as success without re-running side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Mapping

from models.evolution import CandidateStatus

TERMINAL_STATES: FrozenSet[CandidateStatus] = frozenset({
    CandidateStatus.REJECTED,
    CandidateStatus.EXPIRED,
    CandidateStatus.ROLLED_BACK,
    CandidateStatus.BLOCKED,
})

_ALLOWED: Mapping[CandidateStatus, FrozenSet[CandidateStatus]] = {
    CandidateStatus.CAPTURED: frozenset({
        CandidateStatus.PENDING,
        CandidateStatus.BLOCKED,
    }),
    CandidateStatus.PENDING: frozenset({
        CandidateStatus.ACCEPTED,
        CandidateStatus.REJECTED,
        CandidateStatus.SNOOZED,
        CandidateStatus.EXPIRED,
        CandidateStatus.BLOCKED,
    }),
    CandidateStatus.ACCEPTED: frozenset({
        CandidateStatus.PROMOTED_TO_MEMORY,
        CandidateStatus.PROMOTED_TO_SKILL_DRAFT,
        CandidateStatus.ROLLED_BACK,
    }),
    CandidateStatus.SNOOZED: frozenset({
        CandidateStatus.PENDING,
        CandidateStatus.EXPIRED,
    }),
    CandidateStatus.PROMOTED_TO_MEMORY: frozenset({
        CandidateStatus.ROLLED_BACK,
    }),
    CandidateStatus.PROMOTED_TO_SKILL_DRAFT: frozenset({
        CandidateStatus.ROLLED_BACK,
    }),
    CandidateStatus.REJECTED: frozenset(),
    CandidateStatus.EXPIRED: frozenset(),
    CandidateStatus.ROLLED_BACK: frozenset(),
    CandidateStatus.BLOCKED: frozenset(),
}


@dataclass(frozen=True)
class TransitionResult:
    allowed: bool
    no_op: bool
    reason: str


def evaluate_transition(
    current: CandidateStatus,
    target: CandidateStatus,
) -> TransitionResult:
    """Decide whether a status transition is allowed.

    Args:
        current: status currently persisted for the candidate.
        target: status the caller wants to move to.

    Returns:
        TransitionResult with `allowed` (caller may write), `no_op` (target
        equals current — caller should not re-run side effects), and a short
        `reason` suitable for storing in decision_reason or surfacing to logs.
    """

    if current == target:
        return TransitionResult(
            allowed=True,
            no_op=True,
            reason=f"no-op: already in status {current.value}",
        )

    allowed_targets = _ALLOWED.get(current, frozenset())
    if target in allowed_targets:
        return TransitionResult(
            allowed=True,
            no_op=False,
            reason=f"{current.value} -> {target.value}",
        )

    if current in TERMINAL_STATES:
        return TransitionResult(
            allowed=False,
            no_op=False,
            reason=f"forbidden: {current.value} is terminal; cannot transition to {target.value}",
        )

    return TransitionResult(
        allowed=False,
        no_op=False,
        reason=f"forbidden: {current.value} -> {target.value} is not in allowed transitions",
    )


def is_terminal(status: CandidateStatus) -> bool:
    """Return True when the status cannot transition further."""

    return status in TERMINAL_STATES
