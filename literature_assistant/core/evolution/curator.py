"""
Background curator for the evolution candidate store.

Scope:
    - dedupe similar candidates              (sweep; report-only in v1)
    - detect conflicting candidates           (flag; no auto-resolve)
    - expire stale pending candidates         (PENDING -> EXPIRED, reversible
      via re-capture since EXPIRED is terminal)
    - downgrade low-confidence pending items  (PENDING -> SNOOZED, reversible
      via service.mark_pending again)
    - suggest consolidation candidates        (report-only)
    - keep curator writes auditable           (every transition writes
      decision_reason "curator: ...")

Acceptance gates:
    - Curator can be disabled globally (evolution.curator_enabled, default false)
    - Curator changes are reversible (SNOOZED stays in lifecycle; EXPIRED is
      terminal but a fresh re-capture from the same source creates a new
      candidate, so the "expire" is recoverable at the data-source level)
    - Conflicts are surfaced rather than silently overwritten (returned as
      flags in CuratorRunResult; no auto-resolution)

This module is pure-Python over a service handle — no I/O beyond the store
calls the service already makes. It can run on demand via /evolution/curate/run
or be scheduled later by a separate orchestrator.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from models.evolution import CandidateStatus, ExperienceCandidate
from evolution.config import is_curator_llm_judge_enabled
from evolution.curator_llm_judge import (
    JudgeVerdict,
    call_curator_llm_judge,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(ts: str) -> Optional[datetime]:
    """Parse ISO 8601 'YYYY-MM-DDTHH:MM:SSZ' to a tz-aware datetime."""

    if not isinstance(ts, str) or not ts:
        return None
    try:
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts[:-1]).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class CuratorRunResult:
    """Summary of one curator pass.

    `expired` / `demoted` carry the candidate_ids that the curator actually
    transitioned this pass (idempotent: a subsequent run on the same store
    state yields empty lists). `conflicts` and `dedupe_groups` are
    report-only — the curator does NOT auto-resolve them; reviewers act
    through the regular accept/reject/snooze endpoints.
    """

    expired: List[str] = field(default_factory=list)
    demoted: List[str] = field(default_factory=list)
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    dedupe_groups: List[Dict[str, Any]] = field(default_factory=list)
    skipped: Dict[str, int] = field(default_factory=dict)
    scanned_count: int = 0


class EvolutionCurator:
    """Curator pass over the evolution candidate store.

    Pass a configured EvolutionService (or anything that exposes the same
    list / store.transition / get surface). All thresholds are constructor
    args so tests can drive the curator deterministically.
    """

    def __init__(
        self,
        service: Any,
        *,
        stale_threshold_seconds: int = 60 * 60 * 24 * 14,  # 14 days
        low_confidence_threshold: float = 0.35,
        scan_limit: int = 200,
        judge: Optional[Callable[[List[str]], JudgeVerdict]] = None,
        use_llm_judge: Optional[bool] = None,
    ) -> None:
        self.service = service
        self.stale_threshold_seconds = max(0, int(stale_threshold_seconds))
        self.low_confidence_threshold = max(0.0, min(1.0, float(low_confidence_threshold)))
        self.scan_limit = max(1, int(scan_limit))
        # `use_llm_judge=None` defers to the YAML flag; tests pass True/False
        # explicitly to lock behavior independent of config.
        if use_llm_judge is None:
            self._llm_judge_enabled = is_curator_llm_judge_enabled()
        else:
            self._llm_judge_enabled = bool(use_llm_judge)
        # `judge=None` falls back to the default Ark-routed judge; tests
        # inject stubs to avoid real LLM traffic.
        self._judge: Callable[[List[str]], JudgeVerdict] = judge or call_curator_llm_judge

    def run(
        self,
        *,
        workspace_id: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> CuratorRunResult:
        """Single-shot curator pass.

        Acts on candidates in PENDING status only — accepted/rejected/promoted
        rows are owned by reviewer decisions and the promotion path, not the
        curator. EXPIRED / ROLLED_BACK / REJECTED rows are terminal and not
        touched.
        """

        clock = now or datetime.now(timezone.utc)
        candidates: List[ExperienceCandidate] = self.service.list(
            workspace_id=workspace_id,
            status=CandidateStatus.PENDING,
            limit=self.scan_limit,
        )

        expired: List[str] = []
        demoted: List[str] = []
        skipped: Dict[str, int] = defaultdict(int)

        for cand in candidates:
            # Stale-expire takes priority — old enough rows are gone regardless
            if self._is_stale(cand, clock):
                outcome = self.service.store.transition(
                    cand.candidate_id,
                    CandidateStatus.EXPIRED,
                    decided_at=_utc_now_iso(),
                    decision_reason=f"curator: stale > {self.stale_threshold_seconds}s",
                )
                if outcome.transition_applied:
                    expired.append(cand.candidate_id)
                else:
                    skipped["stale_transition_blocked"] += 1
                continue

            if cand.confidence < self.low_confidence_threshold:
                outcome = self.service.store.transition(
                    cand.candidate_id,
                    CandidateStatus.SNOOZED,
                    decided_at=_utc_now_iso(),
                    decision_reason=(
                        f"curator: confidence {cand.confidence:.2f} < "
                        f"threshold {self.low_confidence_threshold:.2f}"
                    ),
                )
                if outcome.transition_applied:
                    demoted.append(cand.candidate_id)
                else:
                    skipped["demote_transition_blocked"] += 1

        # Conflicts / dedupe sweep run over a broader status set — they're
        # report-only so they don't need to gate on PENDING.
        broad = self.service.list(workspace_id=workspace_id, limit=self.scan_limit)
        conflicts = self._detect_conflicts(broad)
        dedupe_groups = self._dedupe_sweep(broad)

        return CuratorRunResult(
            expired=expired,
            demoted=demoted,
            conflicts=conflicts,
            dedupe_groups=dedupe_groups,
            skipped=dict(skipped),
            scanned_count=len(candidates),
        )

    # --- internals -----------------------------------------------------------

    def _is_stale(self, cand: ExperienceCandidate, now: datetime) -> bool:
        created = _parse_iso(cand.created_at)
        if created is None:
            return False
        age_seconds = (now - created).total_seconds()
        return age_seconds > self.stale_threshold_seconds

    def _detect_conflicts(
        self, candidates: List[ExperienceCandidate]
    ) -> List[Dict[str, Any]]:
        """Group candidates by (workspace_id, project_id, memory_type) and
        flag groups that contain BOTH accepted/promoted AND rejected rows.
        When the LLM judge is enabled, each flagged group is then
        sent to the judge for semantic-conflict scoring; the verdict is
        appended as `llm_judge` (report-only — curator still never
        auto-resolves)."""

        grouped: Dict[tuple, List[ExperienceCandidate]] = defaultdict(list)
        for cand in candidates:
            key = (cand.workspace_id, cand.project_id, cand.memory_type.value)
            grouped[key].append(cand)

        conflicts: List[Dict[str, Any]] = []
        for key, group in grouped.items():
            if len(group) < 2:
                continue
            statuses = {c.status for c in group}
            has_positive = bool(statuses & {
                CandidateStatus.ACCEPTED,
                CandidateStatus.PROMOTED_TO_MEMORY,
                CandidateStatus.PROMOTED_TO_SKILL_DRAFT,
            })
            has_negative = bool(statuses & {CandidateStatus.REJECTED})
            if not (has_positive and has_negative):
                continue
            entry: Dict[str, Any] = {
                "workspace_id": key[0],
                "project_id": key[1],
                "memory_type": key[2],
                "candidate_ids": [c.candidate_id for c in group],
                "summary": (
                    f"{len(group)} candidates share "
                    f"workspace/project/memory_type but include both "
                    f"positive ({sorted(s.value for s in statuses & {CandidateStatus.ACCEPTED, CandidateStatus.PROMOTED_TO_MEMORY, CandidateStatus.PROMOTED_TO_SKILL_DRAFT})}) "
                    f"and negative ({sorted(s.value for s in statuses & {CandidateStatus.REJECTED})}) decisions"
                ),
            }
            if self._llm_judge_enabled:
                entry["llm_judge"] = self._judge_bucket(group).to_report_dict()
            conflicts.append(entry)
        return conflicts

    def _judge_bucket(
        self, group: List[ExperienceCandidate]
    ) -> JudgeVerdict:
        """Call the injected judge on a polarity-conflict bucket; never raises."""

        claims = [str(c.claim or "").strip() for c in group if str(c.claim or "").strip()]
        try:
            verdict = self._judge(claims)
        except Exception as exc:  # pragma: no cover - defensive guard
            return JudgeVerdict(
                conflict=False,
                rationale="judge unavailable",
                judged_claim_count=len(claims),
                error=exc.__class__.__name__,
            )
        if not isinstance(verdict, JudgeVerdict):
            return JudgeVerdict(
                conflict=False,
                rationale="judge returned unexpected type",
                judged_claim_count=len(claims),
                error="invalid_verdict",
            )
        return verdict

    def _dedupe_sweep(
        self, candidates: List[ExperienceCandidate]
    ) -> List[Dict[str, Any]]:
        """Group candidates by dedupe_hash and report any groups > 1.

        At write time the store rejects duplicate dedupe_hash inserts; this
        sweep exists as a safety net to surface any historic rows that
        somehow share a hash (e.g. database imported from a backup with
        manual edits)."""

        by_hash: Dict[str, List[ExperienceCandidate]] = defaultdict(list)
        for cand in candidates:
            by_hash[cand.dedupe_hash].append(cand)
        return [
            {
                "dedupe_hash": h,
                "candidate_ids": [c.candidate_id for c in group],
                "count": len(group),
            }
            for h, group in by_hash.items()
            if len(group) > 1
        ]
