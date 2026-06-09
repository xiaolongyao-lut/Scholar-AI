"""
SQLite persistence for the evolution candidate store.

Path: workspace_artifacts/runtime_state/evolution_candidates.sqlite3
       (fixed runtime-state location; do not change without a new ADR)

Style mirrors literature_assistant.core.canonical_event_store.CanonicalEventStore
(open fresh connection per public method; explicit close in finally; CREATE
TABLE IF NOT EXISTS in _init_schema).

Idempotency:
    - dedupe_hash is UNIQUE; insert_or_merge uses INSERT ... ON CONFLICT to
      merge new state onto the existing row without creating a duplicate
      (duplicate dedupe hash: merge or update existing candidate; do not
      create another visible card).
    - Status transitions are gated by state_machine.evaluate_transition; the
      store refuses to write a forbidden transition (returns the prior row
      unchanged) so callers cannot bypass the rules by hitting the store
      directly.

Online backup:
    - backup_to() uses sqlite3.Connection.backup();
      raw file copy is never used while the app may have the database open.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from project_paths import runtime_state_path
from evolution.state_machine import evaluate_transition
from models.evolution import (
    CandidateStatus,
    ExperienceCandidate,
)

DEFAULT_DB_FILENAME = "evolution_candidates.sqlite3"


def default_db_path() -> Path:
    """Return the fixed candidate-store path."""

    path = runtime_state_path(DEFAULT_DB_FILENAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class StoreWriteResult:
    candidate: ExperienceCandidate
    created: bool
    merged: bool
    transition_applied: bool
    reason: str


class EvolutionCandidateStore:
    """SQLite-backed store for ExperienceCandidate rows."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = str(db_path) if db_path else str(default_db_path())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _open(self) -> sqlite3.Connection:
        """Open a connection with concurrency PRAGMAs applied.

        - `journal_mode=WAL`: readers no longer block writers and vice-versa.
          WAL state is per-database-file and persists once set; opening with
          this PRAGMA is idempotent (subsequent opens see the existing WAL).
        - `busy_timeout`: matches the connect(timeout=...) value but is
          enforced consistently across implicit lock acquisitions (not just
          the initial connect handshake).
        - `synchronous=NORMAL`: safe with WAL; durable on commit, only loses
          uncommitted writes on power loss. Faster than FULL without
          sacrificing ACID for committed transactions.
        """

        conn = sqlite3.connect(self.db_path, timeout=10.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:
            # Best-effort PRAGMAs; even if one fails (e.g. read-only fs)
            # the caller can still observe the underlying error on a real
            # write/read. Do not mask the original exception.
            pass
        return conn

    def _init_schema(self) -> None:
        conn = self._open()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS candidates (
                    candidate_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    user_id TEXT,
                    project_id TEXT,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_route TEXT,
                    source_summary TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    claim TEXT NOT NULL,
                    future_use TEXT NOT NULL,
                    evidence_refs JSON NOT NULL,
                    confidence REAL NOT NULL,
                    risk_level TEXT NOT NULL,
                    status TEXT NOT NULL,
                    dedupe_hash TEXT NOT NULL UNIQUE,
                    decision_reason TEXT,
                    rollback_ref TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    decided_at TEXT,
                    promoted_at TEXT
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_candidates_workspace ON candidates(workspace_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_candidates_project ON candidates(project_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_candidates_memory_type ON candidates(memory_type)"
            )
            conn.commit()
        finally:
            conn.close()

    def insert_or_merge(self, candidate: ExperienceCandidate) -> StoreWriteResult:
        """Insert a candidate or merge with an existing row sharing dedupe_hash.

        Merge policy:
            - keep older created_at and existing candidate_id
            - replace title / claim / future_use / source_summary / evidence_refs
              / confidence / risk_level / source_route with the new values
            - keep existing status (status is owned by the state machine, not
              the writer of new content)
            - bump updated_at to the new candidate's updated_at

        Security gate for secret-dedupe-bypass prevention:
            - If the incoming candidate is BLOCKED (secret_scan flagged) and a
              dedupe peer already exists, refuse the merge entirely. Otherwise
              an attacker could write a clean candidate first, then write a
              second one with the same claim but sensitive text in title / future_use,
              and the merge path would overwrite the clean row's fields with
              sensitive text while preserving the clean status.
            - Refusal returns the EXISTING row unchanged with a blocked-payload
              reason. The blocked incoming row is not persisted, so sensitive
              text never lands.
        """

        existing = self._get_by_dedupe_hash(candidate.dedupe_hash)
        if existing is None:
            try:
                self._insert_row(candidate)
            except sqlite3.IntegrityError:
                # TOCTOU race: another writer inserted the same dedupe_hash
                # between our SELECT and INSERT. Re-fetch and fall through to
                # the merge branch so the second writer cleanly merges onto
                # the first writer's row instead of bubbling IntegrityError.
                existing = self._get_by_dedupe_hash(candidate.dedupe_hash)
                if existing is None:
                    # Race-free path: the IntegrityError was for a different
                    # constraint (should not happen at this schema version).
                    # Surface the original error so callers see the real cause.
                    raise
            else:
                return StoreWriteResult(
                    candidate=candidate,
                    created=True,
                    merged=False,
                    transition_applied=False,
                    reason="created",
                )

        if candidate.status == CandidateStatus.BLOCKED:
            return StoreWriteResult(
                candidate=existing,
                created=False,
                merged=False,
                transition_applied=False,
                reason="blocked-secret payload refused at merge time; existing row untouched",
            )

        merged = existing.model_copy(update={
            "title": candidate.title,
            "claim": candidate.claim,
            "future_use": candidate.future_use,
            "source_summary": candidate.source_summary,
            "source_route": candidate.source_route,
            "evidence_refs": candidate.evidence_refs,
            "confidence": candidate.confidence,
            "risk_level": candidate.risk_level,
            "updated_at": candidate.updated_at,
        })
        self._update_row(merged)
        return StoreWriteResult(
            candidate=merged,
            created=False,
            merged=True,
            transition_applied=False,
            reason="merged on dedupe_hash",
        )

    def transition(
        self,
        candidate_id: str,
        target: CandidateStatus,
        *,
        decided_at: str,
        decision_reason: Optional[str] = None,
        rollback_ref: Optional[str] = None,
        promoted_at: Optional[str] = None,
    ) -> StoreWriteResult:
        """Move a candidate to a new status, gated by the state machine.

        Returns StoreWriteResult.transition_applied=False if the transition
        was forbidden or a no-op (idempotent self-transition). The row is
        never mutated for forbidden transitions.
        """

        existing = self.get(candidate_id)
        if existing is None:
            raise KeyError(f"candidate not found: {candidate_id}")

        verdict = evaluate_transition(existing.status, target)
        if not verdict.allowed:
            return StoreWriteResult(
                candidate=existing,
                created=False,
                merged=False,
                transition_applied=False,
                reason=verdict.reason,
            )
        if verdict.no_op:
            return StoreWriteResult(
                candidate=existing,
                created=False,
                merged=False,
                transition_applied=False,
                reason=verdict.reason,
            )

        updates: Dict[str, Any] = {
            "status": target,
            "decided_at": decided_at,
            "updated_at": decided_at,
        }
        if decision_reason is not None:
            updates["decision_reason"] = decision_reason
        if rollback_ref is not None:
            updates["rollback_ref"] = rollback_ref
        if promoted_at is not None:
            updates["promoted_at"] = promoted_at

        new_row = existing.model_copy(update=updates)
        self._update_row(new_row)
        return StoreWriteResult(
            candidate=new_row,
            created=False,
            merged=False,
            transition_applied=True,
            reason=verdict.reason,
        )

    def get(self, candidate_id: str) -> Optional[ExperienceCandidate]:
        conn = self._open()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT " + _COLUMNS + " FROM candidates WHERE candidate_id = ?",
                (candidate_id,),
            )
            row = cursor.fetchone()
            return _row_to_candidate(row) if row else None
        finally:
            conn.close()

    def list(
        self,
        *,
        workspace_id: Optional[str] = None,
        project_id: Optional[str] = None,
        status: Optional[CandidateStatus] = None,
        memory_type: Optional[str] = None,
        sort_by: str = "updated_at",
        limit: int = 50,
        offset: int = 0,
    ) -> List[ExperienceCandidate]:
        clauses, params = self._build_filter_clauses(
            workspace_id=workspace_id,
            project_id=project_id,
            status=status,
            memory_type=memory_type,
        )

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params = list(params) + [limit, offset]

        conn = self._open()
        try:
            cursor = conn.cursor()
            order_by = _candidate_order_by(sort_by)
            cursor.execute(
                f"SELECT {_COLUMNS} FROM candidates{where} "
                f"ORDER BY {order_by} LIMIT ? OFFSET ?",
                tuple(params),
            )
            rows = cursor.fetchall()
            return [_row_to_candidate(row) for row in rows]
        finally:
            conn.close()

    def count(
        self,
        *,
        workspace_id: Optional[str] = None,
        project_id: Optional[str] = None,
        status: Optional[CandidateStatus] = None,
        memory_type: Optional[str] = None,
    ) -> int:
        """Return the total number of candidates matching the same filters as
        :meth:`list`. Pagination-independent; the value is the true filter
        cardinality so the router can return an accurate `total` even when
        the caller asked for a single page."""

        clauses, params = self._build_filter_clauses(
            workspace_id=workspace_id,
            project_id=project_id,
            status=status,
            memory_type=memory_type,
        )
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        conn = self._open()
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT COUNT(*) FROM candidates{where}",
                tuple(params),
            )
            row = cursor.fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()

    @staticmethod
    def _build_filter_clauses(
        *,
        workspace_id: Optional[str],
        project_id: Optional[str],
        status: Optional[CandidateStatus],
        memory_type: Optional[str],
    ) -> tuple[List[str], List[Any]]:
        """Shared WHERE-clause builder for list/count to keep the filter
        semantics identical."""

        clauses: List[str] = []
        params: List[Any] = []
        if workspace_id is not None:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if memory_type is not None:
            clauses.append("memory_type = ?")
            params.append(memory_type)
        return clauses, params

    def count_by_status(self, *, workspace_id: Optional[str] = None) -> Dict[str, int]:
        conn = self._open()
        try:
            cursor = conn.cursor()
            if workspace_id is not None:
                cursor.execute(
                    "SELECT status, COUNT(*) FROM candidates "
                    "WHERE workspace_id = ? GROUP BY status",
                    (workspace_id,),
                )
            else:
                cursor.execute(
                    "SELECT status, COUNT(*) FROM candidates GROUP BY status"
                )
            return {row[0]: int(row[1]) for row in cursor.fetchall()}
        finally:
            conn.close()

    def audit_summary(
        self,
        *,
        workspace_id: Optional[str] = None,
        recent_decision_limit: int = 10,
    ) -> Dict[str, Any]:
        """Operator-facing snapshot for /evolution/audit.

        Read-only roll-up over the candidate table. No raw candidate fields
        (claim / title / future_use / source_summary) leave the store — only
        counts, status / memory_type / source_type breakdowns, and recent
        non-empty decision_reason strings. The decision_reason column is
        free-text but it's only ever written by service / curator /
        promoter code paths (never by user-typed input), so surfacing it
        does not leak user content; sensitive rows have status=BLOCKED
        and their decision_reason is the scanner's own message.
        """

        conn = self._open()
        try:
            cursor = conn.cursor()
            where = ""
            params: List[Any] = []
            if workspace_id is not None:
                where = " WHERE workspace_id = ?"
                params = [workspace_id]

            cursor.execute(f"SELECT COUNT(*) FROM candidates{where}", params)
            total = int(cursor.fetchone()[0])

            cursor.execute(
                f"SELECT status, COUNT(*) FROM candidates{where} GROUP BY status",
                params,
            )
            by_status: Dict[str, int] = {row[0]: int(row[1]) for row in cursor.fetchall()}

            cursor.execute(
                f"SELECT memory_type, COUNT(*) FROM candidates{where} GROUP BY memory_type",
                params,
            )
            by_memory_type: Dict[str, int] = {row[0]: int(row[1]) for row in cursor.fetchall()}

            cursor.execute(
                f"SELECT source_type, COUNT(*) FROM candidates{where} GROUP BY source_type",
                params,
            )
            by_source_type: Dict[str, int] = {row[0]: int(row[1]) for row in cursor.fetchall()}

            promotion_where = " AND " if where else " WHERE "
            promotion_filter = (
                where
                + promotion_where
                + "status IN ('promoted_to_memory', 'promoted_to_skill_draft', 'rolled_back')"
            )
            cursor.execute(
                f"SELECT status, COUNT(*) FROM candidates{promotion_filter} GROUP BY status",
                params,
            )
            promotion_outcomes: Dict[str, int] = {
                row[0]: int(row[1]) for row in cursor.fetchall()
            }

            recent_limit = max(0, int(recent_decision_limit))
            recent_decisions: List[Dict[str, Any]] = []
            if recent_limit > 0:
                cursor.execute(
                    f"SELECT candidate_id, status, decision_reason, decided_at "
                    f"FROM candidates{where} "
                    f"  {'AND' if where else 'WHERE'} decision_reason IS NOT NULL "
                    f"  AND decision_reason != '' "
                    f"ORDER BY COALESCE(decided_at, updated_at) DESC LIMIT ?",
                    [*params, recent_limit],
                )
                for row in cursor.fetchall():
                    cid, status, reason, decided_at = row
                    recent_decisions.append(
                        {
                            "candidate_id": cid,
                            "status": status,
                            # Bound any unexpectedly long reason string so an
                            # audit endpoint can never echo more than a small
                            # fixed amount per row.
                            "decision_reason": (str(reason or ""))[:240],
                            "decided_at": decided_at,
                        }
                    )

            return {
                "workspace_id": workspace_id,
                "total": total,
                "by_status": by_status,
                "by_memory_type": by_memory_type,
                "by_source_type": by_source_type,
                "promotion_outcomes": promotion_outcomes,
                "recent_decisions": recent_decisions,
            }
        finally:
            conn.close()

    def backup_to(self, target_path: str | Path) -> Path:
        """Online backup via sqlite3.Connection.backup()."""

        dst = Path(target_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        source = self._open()
        try:
            destination = sqlite3.connect(str(dst), timeout=10.0)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()
        return dst

    # ----- internals ---------------------------------------------------------

    def _get_by_dedupe_hash(self, dedupe_hash: str) -> Optional[ExperienceCandidate]:
        conn = self._open()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT " + _COLUMNS + " FROM candidates WHERE dedupe_hash = ?",
                (dedupe_hash,),
            )
            row = cursor.fetchone()
            return _row_to_candidate(row) if row else None
        finally:
            conn.close()

    def _insert_row(self, candidate: ExperienceCandidate) -> None:
        conn = self._open()
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"INSERT INTO candidates ({_COLUMNS}) VALUES ({_PLACEHOLDERS})",
                _candidate_to_row(candidate),
            )
            conn.commit()
        finally:
            conn.close()

    def _update_row(self, candidate: ExperienceCandidate) -> None:
        conn = self._open()
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                UPDATE candidates SET
                    workspace_id = ?, user_id = ?, project_id = ?,
                    source_type = ?, source_id = ?, source_route = ?,
                    source_summary = ?, memory_type = ?, title = ?, claim = ?,
                    future_use = ?, evidence_refs = ?, confidence = ?,
                    risk_level = ?, status = ?, dedupe_hash = ?,
                    decision_reason = ?, rollback_ref = ?,
                    created_at = ?, updated_at = ?, decided_at = ?, promoted_at = ?
                WHERE candidate_id = ?
                """,
                _candidate_to_row(candidate)[1:] + (candidate.candidate_id,),
            )
            conn.commit()
        finally:
            conn.close()


_COLUMNS = (
    "candidate_id, workspace_id, user_id, project_id, source_type, source_id, "
    "source_route, source_summary, memory_type, title, claim, future_use, "
    "evidence_refs, confidence, risk_level, status, dedupe_hash, "
    "decision_reason, rollback_ref, created_at, updated_at, decided_at, promoted_at"
)
_PLACEHOLDERS = ", ".join(["?"] * 23)


def _candidate_order_by(sort_by: str) -> str:
    """Return an allowlisted ORDER BY clause for candidate ranking."""
    if sort_by == "confidence":
        return "confidence DESC, updated_at DESC, candidate_id ASC"
    if sort_by == "created_at":
        return "created_at DESC, candidate_id ASC"
    if sort_by != "updated_at":
        raise ValueError(f"unsupported candidate sort_by: {sort_by}")
    return "updated_at DESC, candidate_id ASC"


def _candidate_to_row(candidate: ExperienceCandidate) -> tuple:
    return (
        candidate.candidate_id,
        candidate.workspace_id,
        candidate.user_id,
        candidate.project_id,
        candidate.source_type.value,
        candidate.source_id,
        candidate.source_route,
        candidate.source_summary,
        candidate.memory_type.value,
        candidate.title,
        candidate.claim,
        candidate.future_use,
        json.dumps(candidate.evidence_refs, ensure_ascii=False),
        float(candidate.confidence),
        candidate.risk_level.value,
        candidate.status.value,
        candidate.dedupe_hash,
        candidate.decision_reason,
        candidate.rollback_ref,
        candidate.created_at,
        candidate.updated_at,
        candidate.decided_at,
        candidate.promoted_at,
    )


def _safe_json_loads(value: Any) -> list:
    """Tolerant evidence_refs decoder.

    Bug sweep: raw json.loads would propagate JSONDecodeError out of
    `list(...)` / `get(...)` if a row's evidence_refs column was ever
    corrupted (manual SQL edit, partial migration, etc.). Surface an
    empty list instead so a single bad row cannot poison the entire
    /evolution/candidates response.
    """

    if not value:
        return []
    try:
        decoded = json.loads(value)
    except (ValueError, TypeError):
        return []
    if isinstance(decoded, list):
        return decoded
    return []


def _row_to_candidate(row: tuple) -> ExperienceCandidate:
    return ExperienceCandidate(
        candidate_id=row[0],
        workspace_id=row[1],
        user_id=row[2],
        project_id=row[3],
        source_type=row[4],
        source_id=row[5],
        source_route=row[6],
        source_summary=row[7],
        memory_type=row[8],
        title=row[9],
        claim=row[10],
        future_use=row[11],
        evidence_refs=_safe_json_loads(row[12]),
        confidence=float(row[13]),
        risk_level=row[14],
        status=row[15],
        dedupe_hash=row[16],
        decision_reason=row[17],
        rollback_ref=row[18],
        created_at=row[19],
        updated_at=row[20],
        decided_at=row[21],
        promoted_at=row[22],
    )
