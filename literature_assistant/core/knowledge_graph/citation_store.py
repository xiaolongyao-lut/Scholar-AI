"""Transactional SQLite store for citation mentions and ``cites`` candidates."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast
from uuid import uuid4

from pydantic import ValidationError

from literature_assistant.core.knowledge_graph.citation_models import (
    CitationCaptureReceipt,
    CitationFreshnessStatus,
    CitationMention,
    CitationOutcome,
    CitationReviewDecisionStatus,
    CitationReviewStatus,
    CitesCandidate,
    citation_mention_dedupe_hash,
    cites_candidate_dedupe_hash,
)
from literature_assistant.core.knowledge_graph.citation_lifecycle import (
    CitationLifecycleAxis,
    CitationLifecycleEvent,
    CitationLifecycleStatus,
    CitationLifecycleTransitionResult,
    CitationSourceRevisionApplyReceipt,
    CitationSourceRevisionIdentity,
    CitationSourceRevisionImpact,
    CitationSourceRevisionMismatch,
    CitationSourceRevisionOperation,
    CitationSourceRevisionPreflight,
    CitationSourceRevisionRole,
    citation_source_revision_impact_fingerprint,
    make_lifecycle_event,
    require_freshness_transition,
    require_review_transition,
)

CITATION_STORE_SCHEMA_VERSION = 2
MAX_CITATION_BATCH_RECORDS = 1_024
MAX_CITATION_LIST_LIMIT = 500
MAX_CITATION_SOURCE_REVISION_IMPACTS = 500

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_OUTCOMES = frozenset({"matched", "unmatched", "ambiguous", "over_limit", "failed"})
_REVIEW_STATUSES = frozenset({"candidate", "accepted", "rejected"})
_FRESHNESS_STATUSES = frozenset({"fresh", "stale"})


class CitationStoreError(RuntimeError):
    """Base error for durable citation-store failures."""


class CitationStoreConflictError(CitationStoreError):
    """Raised when one stable identity is reused for different citation data."""


class CitationStoreCorruptionError(CitationStoreError):
    """Raised when a persisted row no longer satisfies the strict model."""


@dataclass(frozen=True, slots=True)
class CitationBatchWriteResult:
    """Canonical records and create/reuse evidence for one atomic save."""

    batch_id: str
    mentions: tuple[CitationMention, ...]
    candidates: tuple[CitesCandidate, ...]
    created_mention_ids: tuple[str, ...]
    created_candidate_ids: tuple[str, ...]
    reused_mention_ids: tuple[str, ...]
    reused_candidate_ids: tuple[str, ...]


class CitationCandidateStore:
    """Project-scoped SQLite persistence supplied with an explicit DB path.

    The store opens a fresh connection for each public operation. ``save_batch``
    uses one ``BEGIN IMMEDIATE`` transaction for every mention and candidate,
    so a candidate mismatch or SQLite failure cannot leave a partial parse.
    Semantic hashes make retries idempotent while retaining new source/parser
    versions as separate records.
    """

    def __init__(self, db_path: str | Path) -> None:
        """Initialize a citation store at the caller-owned project DB path.

        Args:
            db_path: Dedicated project-level SQLite file. No default global
                location is used because citation facts belong to one project.

        Raises:
            ValueError: If the path is empty or names an existing directory.
            CitationStoreError: If SQLite cannot initialize the schema.
        """

        if not str(db_path).strip():
            raise ValueError("db_path must be non-empty")
        resolved = Path(db_path).expanduser().resolve()
        if resolved.exists() and resolved.is_dir():
            raise ValueError("db_path must name a SQLite file, not a directory")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = resolved
        self._init_schema()

    def save_batch(
        self,
        mentions: Sequence[CitationMention],
        candidates: Sequence[CitesCandidate],
    ) -> CitationBatchWriteResult:
        """Persist one parse batch and its directed candidates atomically.

        Args:
            mentions: Every structured parse outcome, including unmatched,
                ambiguous, over-limit, and failed records.
            candidates: Directed edges for unique matched mentions only.

        Returns:
            Canonical stored records plus created/reused identifiers.

        Raises:
            ValueError: If input types, bounds, project, or batch differ.
            CitationStoreConflictError: If a candidate and mention disagree or
                a stable identity is reused for different data.
            CitationStoreError: If SQLite rejects the transaction.
        """

        mention_records = _validate_mentions(mentions)
        candidate_records = _validate_candidates(candidates)
        all_records: tuple[CitationMention | CitesCandidate, ...] = (
            *mention_records,
            *candidate_records,
        )
        if not all_records:
            raise ValueError("save_batch requires at least one citation record")
        if len(all_records) > MAX_CITATION_BATCH_RECORDS:
            raise ValueError(f"save_batch accepts at most {MAX_CITATION_BATCH_RECORDS} records")
        batch_ids = {record.batch_id for record in all_records}
        project_ids = {record.project_id for record in all_records}
        if len(batch_ids) != 1:
            raise ValueError("all citation records in save_batch must share batch_id")
        if len(project_ids) != 1:
            raise ValueError("all citation records in save_batch must share project_id")
        if any(
            record.review_status != "candidate" or record.freshness_status != "fresh"
            for record in all_records
        ):
            raise ValueError(
                "new citation batches must start as review_status=candidate and "
                "freshness_status=fresh"
            )
        _reject_duplicate_input_ids(mention_records, candidate_records)

        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            result = self._save_batch_in_transaction(
                connection,
                mention_records,
                candidate_records,
                batch_id=next(iter(batch_ids)),
            )
            connection.commit()
            return result
        except CitationStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise CitationStoreError("citation batch transaction failed") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def schedule_capture(
        self,
        *,
        project_id: str,
        batch_id: str,
        session_id: str,
        turn_id: str,
        capture_sha256: str,
        expected_mention_count: int,
        expected_candidate_count: int,
    ) -> CitationCaptureReceipt:
        """Create or replay one scheduled asynchronous capture receipt."""

        normalized_project = _normalize_id_filter(project_id, "project_id")
        normalized_batch = _normalize_id_filter(batch_id, "batch_id")
        normalized_session = _normalize_id_filter(session_id, "session_id")
        normalized_turn = _normalize_id_filter(turn_id, "turn_id")
        normalized_hash = str(capture_sha256 or "").strip().lower()
        if not _SHA256_RE.fullmatch(normalized_hash):
            raise ValueError("capture_sha256 must use sha256:<64 lowercase hex>")
        mention_count = _capture_count(expected_mention_count, "expected_mention_count")
        candidate_count = _capture_count(expected_candidate_count, "expected_candidate_count")
        if mention_count + candidate_count > MAX_CITATION_BATCH_RECORDS:
            raise ValueError(
                f"citation capture accepts at most {MAX_CITATION_BATCH_RECORDS} records"
            )
        scheduled_at = datetime.now(timezone.utc)
        receipt_seed = f"{normalized_project}\x00{normalized_batch}\x00{normalized_hash}"
        receipt_id = f"citation-capture-{hashlib.sha256(receipt_seed.encode('utf-8')).hexdigest()[:32]}"
        receipt = CitationCaptureReceipt(
            receipt_id=receipt_id,
            project_id=normalized_project,
            batch_id=normalized_batch,
            session_id=normalized_session,
            turn_id=normalized_turn,
            capture_sha256=normalized_hash,
            status="scheduled",
            expected_mention_count=mention_count,
            expected_candidate_count=candidate_count,
            scheduled_at=scheduled_at,
        )

        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing_row = connection.execute(
                """
                SELECT raw_json FROM citation_capture_receipts
                WHERE project_id = ? AND batch_id = ?
                """,
                (normalized_project, normalized_batch),
            ).fetchone()
            if existing_row is not None:
                existing = _row_to_capture_receipt(existing_row)
                identity = (
                    existing.session_id,
                    existing.turn_id,
                    existing.capture_sha256,
                    existing.expected_mention_count,
                    existing.expected_candidate_count,
                )
                requested_identity = (
                    normalized_session,
                    normalized_turn,
                    normalized_hash,
                    mention_count,
                    candidate_count,
                )
                if identity != requested_identity:
                    raise CitationStoreConflictError(
                        "citation capture batch identity changed"
                    )
                connection.commit()
                return existing
            connection.execute(
                """
                INSERT INTO citation_capture_receipts (
                    receipt_id, project_id, batch_id, session_id, turn_id,
                    status, capture_sha256, scheduled_at, completed_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    receipt.receipt_id,
                    receipt.project_id,
                    receipt.batch_id,
                    receipt.session_id,
                    receipt.turn_id,
                    receipt.status,
                    receipt.capture_sha256,
                    _timestamp(receipt.scheduled_at),
                    receipt.model_dump_json(exclude_none=False),
                ),
            )
            connection.commit()
            return receipt
        except CitationStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise CitationStoreError("citation capture scheduling failed") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save_batch_for_capture(
        self,
        receipt_id: str,
        mentions: Sequence[CitationMention],
        candidates: Sequence[CitesCandidate],
    ) -> CitationCaptureReceipt:
        """Atomically store one batch and complete its scheduled receipt."""

        normalized_receipt = _normalize_id_filter(receipt_id, "receipt_id")
        mention_records = _validate_mentions(mentions)
        candidate_records = _validate_candidates(candidates)
        if not mention_records and not candidate_records:
            return self.complete_empty_capture(normalized_receipt)
        if len(mention_records) + len(candidate_records) > MAX_CITATION_BATCH_RECORDS:
            raise ValueError(
                f"citation capture accepts at most {MAX_CITATION_BATCH_RECORDS} records"
            )

        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT raw_json FROM citation_capture_receipts WHERE receipt_id = ?",
                (normalized_receipt,),
            ).fetchone()
            if row is None:
                raise CitationStoreConflictError("citation capture receipt not found")
            receipt = _row_to_capture_receipt(row)
            project_ids = {record.project_id for record in (*mention_records, *candidate_records)}
            batch_ids = {record.batch_id for record in (*mention_records, *candidate_records)}
            session_ids = {record.session_id for record in (*mention_records, *candidate_records)}
            turn_ids = {record.turn_id for record in (*mention_records, *candidate_records)}
            if project_ids != {receipt.project_id} or batch_ids != {receipt.batch_id}:
                raise CitationStoreConflictError("citation capture project or batch identity changed")
            if session_ids != {receipt.session_id} or turn_ids != {receipt.turn_id}:
                raise CitationStoreConflictError("citation capture session or turn identity changed")
            if len(mention_records) != receipt.expected_mention_count:
                raise CitationStoreConflictError("citation capture mention count changed")
            if len(candidate_records) != receipt.expected_candidate_count:
                raise CitationStoreConflictError("citation capture candidate count changed")
            current_hash = citation_capture_sha256(
                batch_id=receipt.batch_id,
                mentions=mention_records,
                candidates=candidate_records,
            )
            if current_hash != receipt.capture_sha256:
                raise CitationStoreConflictError("citation capture payload changed")
            if receipt.status == "succeeded":
                connection.commit()
                return receipt
            if receipt.status == "failed":
                raise CitationStoreConflictError("failed citation capture cannot be replayed")

            result = self._save_batch_in_transaction(
                connection,
                mention_records,
                candidate_records,
                batch_id=receipt.batch_id,
            )
            completed = _completed_capture_receipt(receipt, result=result)
            update = connection.execute(
                """
                UPDATE citation_capture_receipts
                SET status = ?, completed_at = ?, raw_json = ?
                WHERE receipt_id = ? AND status = 'scheduled'
                """,
                (
                    completed.status,
                    _capture_completion_timestamp(completed),
                    completed.model_dump_json(exclude_none=False),
                    completed.receipt_id,
                ),
            )
            if update.rowcount != 1:
                raise CitationStoreConflictError(
                    "citation capture receipt changed during commit"
                )
            connection.commit()
            return completed
        except CitationStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise CitationStoreError("citation capture transaction failed") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def complete_empty_capture(self, receipt_id: str) -> CitationCaptureReceipt:
        """Complete an explicitly empty scheduled capture."""

        normalized_receipt = _normalize_id_filter(receipt_id, "receipt_id")
        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT raw_json FROM citation_capture_receipts WHERE receipt_id = ?",
                (normalized_receipt,),
            ).fetchone()
            if row is None:
                raise CitationStoreConflictError("citation capture receipt not found")
            receipt = _row_to_capture_receipt(row)
            if receipt.status == "succeeded":
                connection.commit()
                return receipt
            if receipt.status == "failed":
                raise CitationStoreConflictError("failed citation capture cannot be completed")
            if receipt.expected_mention_count or receipt.expected_candidate_count:
                raise CitationStoreConflictError("non-empty citation capture requires batch records")
            completed = _completed_capture_receipt(receipt, result=None)
            update = connection.execute(
                """
                UPDATE citation_capture_receipts
                SET status = ?, completed_at = ?, raw_json = ?
                WHERE receipt_id = ? AND status = 'scheduled'
                """,
                (
                    completed.status,
                    _capture_completion_timestamp(completed),
                    completed.model_dump_json(exclude_none=False),
                    completed.receipt_id,
                ),
            )
            if update.rowcount != 1:
                raise CitationStoreConflictError(
                    "citation capture receipt changed during completion"
                )
            connection.commit()
            return completed
        except CitationStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise CitationStoreError("empty citation capture completion failed") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def fail_capture(
        self,
        receipt_id: str,
        *,
        error_code: str,
    ) -> CitationCaptureReceipt:
        """Mark a scheduled capture failed without retaining diagnostics."""

        normalized_receipt = _normalize_id_filter(receipt_id, "receipt_id")
        normalized_error = str(error_code or "").strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_:-]{0,95}", normalized_error):
            raise ValueError("error_code has an unsupported shape")
        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT raw_json FROM citation_capture_receipts WHERE receipt_id = ?",
                (normalized_receipt,),
            ).fetchone()
            if row is None:
                raise CitationStoreConflictError("citation capture receipt not found")
            receipt = _row_to_capture_receipt(row)
            if receipt.status == "failed":
                if receipt.error_code != normalized_error:
                    raise CitationStoreConflictError("citation capture failure code changed")
                connection.commit()
                return receipt
            if receipt.status == "succeeded":
                raise CitationStoreConflictError("successful citation capture cannot fail")
            failed_payload = receipt.model_dump(mode="python")
            failed_payload.update(
                {
                    "status": "failed",
                    "error_code": normalized_error,
                    "completed_at": datetime.now(timezone.utc),
                }
            )
            failed = CitationCaptureReceipt.model_validate(failed_payload)
            update = connection.execute(
                """
                UPDATE citation_capture_receipts
                SET status = ?, completed_at = ?, raw_json = ?
                WHERE receipt_id = ? AND status = 'scheduled'
                """,
                (
                    failed.status,
                    _capture_completion_timestamp(failed),
                    failed.model_dump_json(exclude_none=False),
                    failed.receipt_id,
                ),
            )
            if update.rowcount != 1:
                raise CitationStoreConflictError(
                    "citation capture receipt changed during failure commit"
                )
            connection.commit()
            return failed
        except CitationStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise CitationStoreError("citation capture failure commit failed") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_capture_receipt(self, receipt_id: str) -> CitationCaptureReceipt | None:
        """Return one capture receipt by stable id."""

        normalized_receipt = _normalize_id_filter(receipt_id, "receipt_id")
        with closing(self._open_or_raise()) as connection:
            row = connection.execute(
                "SELECT raw_json FROM citation_capture_receipts WHERE receipt_id = ?",
                (normalized_receipt,),
            ).fetchone()
        return None if row is None else _row_to_capture_receipt(row)

    def list_capture_receipts(
        self,
        *,
        project_id: str,
        session_id: str | None = None,
        turn_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[CitationCaptureReceipt, ...]:
        """List bounded project capture receipts with allowlisted filters."""

        where = ["project_id = ?"]
        parameters: list[object] = [_normalize_id_filter(project_id, "project_id")]
        for column, value in (("session_id", session_id), ("turn_id", turn_id)):
            if value is not None:
                where.append(f"{column} = ?")
                parameters.append(_normalize_id_filter(value, column))
        if status is not None:
            normalized_status = str(status).strip().lower()
            if normalized_status not in {"scheduled", "succeeded", "failed"}:
                raise ValueError("unsupported citation capture status")
            where.append("status = ?")
            parameters.append(normalized_status)
        bounded_limit, bounded_offset = _pagination(limit, offset)
        parameters.extend((bounded_limit, bounded_offset))
        query = (
            "SELECT raw_json FROM citation_capture_receipts WHERE "
            + " AND ".join(where)
            + " ORDER BY scheduled_at ASC, receipt_id ASC LIMIT ? OFFSET ?"
        )
        with closing(self._open_or_raise()) as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return tuple(_row_to_capture_receipt(row) for row in rows)

    def get_mention(self, mention_id: str) -> CitationMention | None:
        """Read one citation mention by stable id.

        Args:
            mention_id: Strict local mention identifier.

        Returns:
            The validated record, or ``None`` when the id is absent.
        """

        normalized_id = _normalize_id_filter(mention_id, "mention_id")
        with closing(self._open_or_raise()) as connection:
            row = connection.execute(
                "SELECT raw_json FROM citation_mentions WHERE mention_id = ?",
                (normalized_id,),
            ).fetchone()
        return _row_to_mention(row) if row is not None else None

    def get_candidate(self, candidate_id: str) -> CitesCandidate | None:
        """Read one directed ``cites`` candidate by stable id.

        Args:
            candidate_id: Strict local candidate identifier.

        Returns:
            The validated candidate, or ``None`` when the id is absent.
        """

        normalized_id = _normalize_id_filter(candidate_id, "candidate_id")
        with closing(self._open_or_raise()) as connection:
            row = connection.execute(
                "SELECT raw_json FROM cites_candidates WHERE candidate_id = ?",
                (normalized_id,),
            ).fetchone()
        return _row_to_candidate(row) if row is not None else None

    def list_mentions(
        self,
        *,
        project_id: str | None = None,
        batch_id: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        outcome: CitationOutcome | None = None,
        review_status: CitationReviewStatus | None = None,
        freshness_status: CitationFreshnessStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[CitationMention, ...]:
        """List bounded mention records using allowlisted equality filters.

        Args:
            project_id: Optional project equality filter.
            batch_id: Optional shared parser-batch filter.
            session_id: Optional SmartRead session filter.
            turn_id: Optional answer-turn filter.
            outcome: Optional structured resolution outcome.
            review_status: Optional human-review axis filter.
            freshness_status: Optional source-freshness axis filter.
            limit: Maximum records, from 1 through 500.
            offset: Non-negative pagination offset.

        Returns:
            Validated records ordered by creation time and stable id.
        """

        where, parameters = _common_filters(
            project_id=project_id,
            batch_id=batch_id,
            session_id=session_id,
            turn_id=turn_id,
            review_status=review_status,
            freshness_status=freshness_status,
        )
        if outcome is not None:
            if outcome not in _OUTCOMES:
                raise ValueError(f"unsupported citation outcome: {outcome!r}")
            where.append("outcome = ?")
            parameters.append(outcome)
        bounded_limit, bounded_offset = _pagination(limit, offset)
        query = "SELECT raw_json FROM citation_mentions"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY created_at ASC, mention_id ASC LIMIT ? OFFSET ?"
        parameters.extend((bounded_limit, bounded_offset))
        with closing(self._open_or_raise()) as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return tuple(_row_to_mention(row) for row in rows)

    def list_candidates(
        self,
        *,
        project_id: str | None = None,
        batch_id: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        source_material_id: str | None = None,
        target_material_id: str | None = None,
        review_status: CitationReviewStatus | None = None,
        freshness_status: CitationFreshnessStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[CitesCandidate, ...]:
        """List bounded candidate edges using allowlisted equality filters.

        Args:
            project_id: Optional project equality filter.
            batch_id: Optional shared parser-batch filter.
            session_id: Optional SmartRead session filter.
            turn_id: Optional answer-turn filter.
            source_material_id: Optional citing-material filter.
            target_material_id: Optional cited-material filter.
            review_status: Optional human-review axis filter.
            freshness_status: Optional source-freshness axis filter.
            limit: Maximum records, from 1 through 500.
            offset: Non-negative pagination offset.

        Returns:
            Validated directed candidates ordered by creation time and id.
        """

        where, parameters = _common_filters(
            project_id=project_id,
            batch_id=batch_id,
            session_id=session_id,
            turn_id=turn_id,
            review_status=review_status,
            freshness_status=freshness_status,
        )
        for column, value in (
            ("source_material_id", source_material_id),
            ("target_material_id", target_material_id),
        ):
            if value is not None:
                where.append(f"{column} = ?")
                parameters.append(_normalize_id_filter(value, column))
        bounded_limit, bounded_offset = _pagination(limit, offset)
        query = "SELECT raw_json FROM cites_candidates"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY created_at ASC, candidate_id ASC LIMIT ? OFFSET ?"
        parameters.extend((bounded_limit, bounded_offset))
        with closing(self._open_or_raise()) as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return tuple(_row_to_candidate(row) for row in rows)

    def transition_candidate_review(
        self,
        candidate_id: str,
        *,
        expected_current_status: CitationReviewStatus,
        target_status: CitationReviewDecisionStatus,
        reason: str,
        changed_by: str,
        occurred_at: datetime | None = None,
    ) -> CitationLifecycleTransitionResult:
        """Commit one explicit candidate review decision with its bound mention.

        Args:
            candidate_id: Stable directed candidate identifier.
            expected_current_status: Caller-observed review status used for CAS.
            target_status: Human decision, either ``accepted`` or ``rejected``.
            reason: Non-empty bounded audit reason.
            changed_by: Stable local reviewer identifier.
            occurred_at: Optional aware timestamp for deterministic callers.

        Returns:
            Canonical candidate, mention, and audit event committed together.

        Raises:
            KeyError: If the candidate does not exist.
            ValueError: If the requested state transition is invalid.
            CitationStoreConflictError: If the expected status is stale.
            CitationStoreError: If SQLite cannot commit the complete transition.
        """

        if expected_current_status not in _REVIEW_STATUSES:
            raise ValueError(f"unsupported expected review status: {expected_current_status!r}")
        if target_status not in {"accepted", "rejected"}:
            raise ValueError(f"unsupported target review status: {target_status!r}")
        return self._transition_candidate_lifecycle(
            candidate_id,
            axis="review",
            expected_current_status=expected_current_status,
            target_status=target_status,
            reason=reason,
            changed_by=changed_by,
            occurred_at=occurred_at,
        )

    def transition_candidate_freshness(
        self,
        candidate_id: str,
        *,
        expected_current_status: CitationFreshnessStatus,
        target_status: CitationFreshnessStatus,
        reason: str,
        changed_by: str,
        occurred_at: datetime | None = None,
    ) -> CitationLifecycleTransitionResult:
        """Commit one fresh/stale transition without changing review status.

        Args:
            candidate_id: Stable directed candidate identifier.
            expected_current_status: Caller-observed freshness status for CAS.
            target_status: Opposite freshness status to commit.
            reason: Non-empty bounded audit reason.
            changed_by: Stable local actor identifier.
            occurred_at: Optional aware timestamp for deterministic callers.

        Returns:
            Canonical candidate, mention, and audit event committed together.

        Raises:
            KeyError: If the candidate does not exist.
            ValueError: If the requested state transition is invalid.
            CitationStoreConflictError: If the expected status is stale.
            CitationStoreError: If SQLite cannot commit the complete transition.
        """

        if expected_current_status not in _FRESHNESS_STATUSES:
            raise ValueError(f"unsupported expected freshness status: {expected_current_status!r}")
        if target_status not in _FRESHNESS_STATUSES:
            raise ValueError(f"unsupported target freshness status: {target_status!r}")
        if target_status == "fresh":
            raise ValueError(
                "stale citation candidates require provenance-bound source revision revalidation"
            )
        return self._transition_candidate_lifecycle(
            candidate_id,
            axis="freshness",
            expected_current_status=expected_current_status,
            target_status=target_status,
            reason=reason,
            changed_by=changed_by,
            occurred_at=occurred_at,
        )

    def preflight_source_revision(
        self,
        *,
        project_id: str,
        operation: CitationSourceRevisionOperation,
        current_identity: CitationSourceRevisionIdentity,
    ) -> CitationSourceRevisionPreflight:
        """Return one bounded, read-only material revision impact set."""

        normalized_project_id = _normalize_id_filter(project_id, "project_id")
        with closing(self._open_or_raise()) as connection:
            return self._preflight_source_revision_in_connection(
                connection,
                project_id=normalized_project_id,
                operation=operation,
                current_identity=current_identity,
            )

    def apply_source_revision(
        self,
        *,
        project_id: str,
        operation: CitationSourceRevisionOperation,
        current_identity: CitationSourceRevisionIdentity,
        expected_impact_fingerprint: str,
        reason: str,
        changed_by: str,
        validated_candidate_ids: Sequence[str] = (),
    ) -> CitationSourceRevisionApplyReceipt:
        """Atomically apply an exact preflight and persist lifecycle events."""

        normalized_project_id = _normalize_id_filter(project_id, "project_id")
        expected_fingerprint = expected_impact_fingerprint.strip().lower()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_fingerprint):
            raise ValueError("expected_impact_fingerprint must use sha256:<64 lowercase hex>")
        normalized_validated_ids = tuple(
            _normalize_id_filter(candidate_id, "validated_candidate_ids")
            for candidate_id in validated_candidate_ids
        )
        if len(normalized_validated_ids) != len(set(normalized_validated_ids)):
            raise ValueError("validated_candidate_ids must not contain duplicates")
        if len(normalized_validated_ids) > MAX_CITATION_SOURCE_REVISION_IMPACTS:
            raise ValueError("validated_candidate_ids exceeds the bounded apply limit")
        if operation == "mark_stale" and normalized_validated_ids:
            raise ValueError("mark_stale does not accept candidate validation confirmations")
        if operation == "revalidate" and not normalized_validated_ids:
            raise ValueError("revalidate requires explicit validated_candidate_ids")
        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            preflight = self._preflight_source_revision_in_connection(
                connection,
                project_id=normalized_project_id,
                operation=operation,
                current_identity=current_identity,
            )
            if preflight.impact_fingerprint != expected_fingerprint:
                raise CitationStoreConflictError(
                    "citation source revision impact changed after preflight"
                )
            if not preflight.impacts:
                raise CitationStoreConflictError(
                    f"no citation candidates require {operation}"
                )
            impacted_candidate_ids = tuple(
                impact.candidate_id for impact in preflight.impacts
            )
            if operation == "revalidate" and set(normalized_validated_ids) != set(
                impacted_candidate_ids
            ):
                raise CitationStoreConflictError(
                    "validated_candidate_ids do not match the current revalidation impact"
                )

            target_status: CitationFreshnessStatus = (
                "stale" if operation == "mark_stale" else "fresh"
            )
            receipt_id = f"citation-source-revision-{uuid4().hex}"
            events: list[CitationLifecycleEvent] = []
            for impact in preflight.impacts:
                row = connection.execute(
                    """
                    SELECT
                        candidate.raw_json AS candidate_raw_json,
                        candidate.review_status AS candidate_review_status,
                        candidate.freshness_status AS candidate_freshness_status,
                        candidate.updated_at AS candidate_updated_at,
                        mention.raw_json AS mention_raw_json,
                        mention.review_status AS mention_review_status,
                        mention.freshness_status AS mention_freshness_status,
                        mention.updated_at AS mention_updated_at
                    FROM cites_candidates AS candidate
                    JOIN citation_mentions AS mention
                      ON mention.mention_id = candidate.mention_id
                    WHERE candidate.candidate_id = ? AND candidate.project_id = ?
                    """,
                    (impact.candidate_id, normalized_project_id),
                ).fetchone()
                if row is None:
                    raise CitationStoreConflictError(
                        "citation source revision candidate disappeared during apply"
                    )
                candidate, mention = _lifecycle_pair_from_row(row)
                if candidate.freshness_status != impact.expected_freshness_status:
                    raise CitationStoreConflictError(
                        "citation freshness changed during source revision apply"
                    )
                transition_time = _transition_timestamp(
                    None,
                    candidate_updated_at=candidate.updated_at,
                    mention_updated_at=mention.updated_at,
                )
                candidate_payload = candidate.model_dump(mode="python")
                mention_payload = mention.model_dump(mode="python")
                candidate_payload["freshness_status"] = target_status
                mention_payload["freshness_status"] = target_status
                candidate_payload["updated_at"] = transition_time
                mention_payload["updated_at"] = transition_time
                updated_candidate = CitesCandidate.model_validate(candidate_payload)
                updated_mention = CitationMention.model_validate(mention_payload)
                _require_candidate_matches_mention(updated_candidate, updated_mention)
                event = make_lifecycle_event(
                    candidate=updated_candidate,
                    axis="freshness",
                    from_status=impact.expected_freshness_status,
                    to_status=target_status,
                    reason=reason,
                    changed_by=changed_by,
                    occurred_at=transition_time,
                    source_revision_receipt_id=receipt_id,
                    source_revision_operation=operation,
                    source_revision_identity=current_identity,
                    source_revision_impact_fingerprint=preflight.impact_fingerprint,
                )
                timestamp = _timestamp(transition_time)
                mention_update = connection.execute(
                    """
                    UPDATE citation_mentions
                    SET freshness_status = ?, updated_at = ?, raw_json = ?
                    WHERE mention_id = ? AND freshness_status = ? AND updated_at = ?
                    """,
                    (
                        target_status,
                        timestamp,
                        updated_mention.model_dump_json(exclude_none=False),
                        updated_mention.mention_id,
                        impact.expected_freshness_status,
                        row["mention_updated_at"],
                    ),
                )
                candidate_update = connection.execute(
                    """
                    UPDATE cites_candidates
                    SET freshness_status = ?, updated_at = ?, raw_json = ?
                    WHERE candidate_id = ? AND freshness_status = ? AND updated_at = ?
                    """,
                    (
                        target_status,
                        timestamp,
                        updated_candidate.model_dump_json(exclude_none=False),
                        updated_candidate.candidate_id,
                        impact.expected_freshness_status,
                        row["candidate_updated_at"],
                    ),
                )
                if mention_update.rowcount != 1 or candidate_update.rowcount != 1:
                    raise CitationStoreConflictError(
                        "citation source revision changed during apply"
                    )
                connection.execute(
                    """
                    INSERT INTO citation_lifecycle_events (
                        event_id, candidate_id, mention_id, project_id, batch_id,
                        axis, from_status, to_status, reason, changed_by,
                        occurred_at, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.candidate_id,
                        event.mention_id,
                        event.project_id,
                        event.batch_id,
                        event.axis,
                        event.from_status,
                        event.to_status,
                        event.reason,
                        event.changed_by,
                        timestamp,
                        event.model_dump_json(exclude_none=False),
                    ),
                )
                events.append(event)
            connection.commit()
            return CitationSourceRevisionApplyReceipt(
                receipt_id=receipt_id,
                project_id=normalized_project_id,
                operation=operation,
                current_identity=current_identity,
                impact_fingerprint=preflight.impact_fingerprint,
                candidate_ids=tuple(impact.candidate_id for impact in preflight.impacts),
                events=tuple(events),
                occurred_at=max(event.occurred_at for event in events),
            )
        except (CitationStoreError, ValueError):
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise CitationStoreError("citation source revision apply failed") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _preflight_source_revision_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        operation: CitationSourceRevisionOperation,
        current_identity: CitationSourceRevisionIdentity,
    ) -> CitationSourceRevisionPreflight:
        if operation not in {"mark_stale", "revalidate"}:
            raise ValueError(f"unsupported source revision operation: {operation!r}")
        rows = connection.execute(
            """
            SELECT raw_json FROM cites_candidates
            WHERE project_id = ? AND (
                source_material_id = ? OR target_material_id = ?
            )
            ORDER BY created_at ASC, candidate_id ASC
            LIMIT ?
            """,
            (
                project_id,
                current_identity.material_id,
                current_identity.material_id,
                MAX_CITATION_SOURCE_REVISION_IMPACTS + 1,
            ),
        ).fetchall()
        if len(rows) > MAX_CITATION_SOURCE_REVISION_IMPACTS:
            raise CitationStoreConflictError(
                "citation source revision impact exceeds the bounded apply limit"
            )
        impacts: list[CitationSourceRevisionImpact] = []
        for row in rows:
            candidate = _row_to_candidate(row)
            if candidate.project_id != project_id:
                raise CitationStoreCorruptionError("citation candidate project identity drifted")
            role: CitationSourceRevisionRole
            comparisons: tuple[
                tuple[CitationSourceRevisionMismatch, str, str],
                ...,
            ]
            if candidate.source_material_id == current_identity.material_id:
                role = "source"
                effective_identity = self._latest_revalidated_identity(
                    connection,
                    candidate_id=candidate.candidate_id,
                    material_id=current_identity.material_id,
                )
                comparisons = (
                    (
                        "source_fingerprint",
                        effective_identity.source_fingerprint
                        if effective_identity is not None
                        else candidate.source_fingerprint,
                        current_identity.source_fingerprint,
                    ),
                    (
                        "source_version",
                        effective_identity.source_version
                        if effective_identity is not None
                        else candidate.source_version,
                        current_identity.source_version,
                    ),
                    (
                        "extractor_version",
                        effective_identity.extractor_version
                        if effective_identity is not None
                        else candidate.extractor_version,
                        current_identity.extractor_version,
                    ),
                    (
                        "parser_version",
                        effective_identity.parser_version
                        if effective_identity is not None
                        else candidate.parser_version,
                        current_identity.parser_version,
                    ),
                )
            else:
                role = "target"
                effective_identity = self._latest_revalidated_identity(
                    connection,
                    candidate_id=candidate.candidate_id,
                    material_id=current_identity.material_id,
                )
                comparisons = (
                    (
                        "target_fingerprint",
                        effective_identity.source_fingerprint
                        if effective_identity is not None
                        else candidate.target_fingerprint,
                        current_identity.source_fingerprint,
                    ),
                )
            mismatches = tuple(
                field_name
                for field_name, stored, current in comparisons
                if stored != current
            )
            should_include = (
                operation == "mark_stale"
                and candidate.freshness_status == "fresh"
                and bool(mismatches)
            ) or (
                operation == "revalidate"
                and candidate.freshness_status == "stale"
            )
            if not should_include:
                continue
            impacts.append(
                CitationSourceRevisionImpact(
                    candidate_id=candidate.candidate_id,
                    mention_id=candidate.mention_id,
                    material_role=role,
                    mismatch_fields=mismatches,
                    expected_freshness_status=candidate.freshness_status,
                    expected_updated_at=candidate.updated_at,
                )
            )
        impact_tuple = tuple(impacts)
        fingerprint = citation_source_revision_impact_fingerprint(
            project_id=project_id,
            operation=operation,
            current_identity=current_identity,
            impacts=impact_tuple,
        )
        return CitationSourceRevisionPreflight(
            project_id=project_id,
            operation=operation,
            current_identity=current_identity,
            impacts=impact_tuple,
            impact_fingerprint=fingerprint,
        )

    @staticmethod
    def _latest_revalidated_identity(
        connection: sqlite3.Connection,
        *,
        candidate_id: str,
        material_id: str,
    ) -> CitationSourceRevisionIdentity | None:
        rows = connection.execute(
            """
            SELECT raw_json FROM citation_lifecycle_events
            WHERE candidate_id = ? AND axis = 'freshness' AND to_status = 'fresh'
            ORDER BY occurred_at DESC, event_id DESC
            """,
            (candidate_id,),
        ).fetchall()
        for row in rows:
            event = _row_to_lifecycle_event(row)
            identity = event.source_revision_identity
            if (
                event.source_revision_operation == "revalidate"
                and identity is not None
                and identity.material_id == material_id
            ):
                return identity
        return None

    def list_transition_events(
        self,
        *,
        candidate_id: str | None = None,
        axis: CitationLifecycleAxis | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[CitationLifecycleEvent, ...]:
        """List bounded lifecycle audit events in commit order.

        Args:
            candidate_id: Optional exact candidate filter.
            axis: Optional review or freshness filter.
            limit: Maximum rows from 1 through 500.
            offset: Non-negative pagination offset.

        Returns:
            Validated lifecycle events ordered by timestamp and stable id.
        """

        where: list[str] = []
        parameters: list[object] = []
        if candidate_id is not None:
            where.append("candidate_id = ?")
            parameters.append(_normalize_id_filter(candidate_id, "candidate_id"))
        if axis is not None:
            if axis not in {"review", "freshness"}:
                raise ValueError(f"unsupported citation lifecycle axis: {axis!r}")
            where.append("axis = ?")
            parameters.append(axis)
        bounded_limit, bounded_offset = _pagination(limit, offset)
        query = "SELECT raw_json FROM citation_lifecycle_events"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY occurred_at ASC, event_id ASC LIMIT ? OFFSET ?"
        parameters.extend((bounded_limit, bounded_offset))
        with closing(self._open_or_raise()) as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return tuple(_row_to_lifecycle_event(row) for row in rows)

    def _transition_candidate_lifecycle(
        self,
        candidate_id: str,
        *,
        axis: CitationLifecycleAxis,
        expected_current_status: CitationLifecycleStatus,
        target_status: CitationLifecycleStatus,
        reason: str,
        changed_by: str,
        occurred_at: datetime | None,
    ) -> CitationLifecycleTransitionResult:
        normalized_id = _normalize_id_filter(candidate_id, "candidate_id")
        status_column = "review_status" if axis == "review" else "freshness_status"
        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT
                    candidate.raw_json AS candidate_raw_json,
                    candidate.review_status AS candidate_review_status,
                    candidate.freshness_status AS candidate_freshness_status,
                    candidate.updated_at AS candidate_updated_at,
                    mention.raw_json AS mention_raw_json,
                    mention.review_status AS mention_review_status,
                    mention.freshness_status AS mention_freshness_status,
                    mention.updated_at AS mention_updated_at
                FROM cites_candidates AS candidate
                JOIN citation_mentions AS mention
                  ON mention.mention_id = candidate.mention_id
                WHERE candidate.candidate_id = ?
                """,
                (normalized_id,),
            ).fetchone()
            if row is None:
                raise KeyError(normalized_id)
            candidate, mention = _lifecycle_pair_from_row(row)
            current_status = (
                candidate.review_status if axis == "review" else candidate.freshness_status
            )
            mention_status = (
                mention.review_status if axis == "review" else mention.freshness_status
            )
            if mention_status != current_status:
                raise CitationStoreCorruptionError(
                    f"candidate and mention disagree on {status_column}"
                )
            if current_status != expected_current_status:
                raise CitationStoreConflictError(
                    f"expected {status_column}={expected_current_status}, found {current_status}"
                )
            if axis == "review":
                require_review_transition(
                    candidate.review_status,
                    cast(CitationReviewDecisionStatus, target_status),
                )
            else:
                require_freshness_transition(
                    candidate.freshness_status,
                    cast(CitationFreshnessStatus, target_status),
                )

            transition_time = _transition_timestamp(
                occurred_at,
                candidate_updated_at=candidate.updated_at,
                mention_updated_at=mention.updated_at,
            )
            candidate_payload = candidate.model_dump(mode="python")
            mention_payload = mention.model_dump(mode="python")
            candidate_payload[status_column] = target_status
            mention_payload[status_column] = target_status
            candidate_payload["updated_at"] = transition_time
            mention_payload["updated_at"] = transition_time
            updated_candidate = CitesCandidate.model_validate(candidate_payload)
            updated_mention = CitationMention.model_validate(mention_payload)
            _require_candidate_matches_mention(updated_candidate, updated_mention)
            event = make_lifecycle_event(
                candidate=updated_candidate,
                axis=axis,
                from_status=current_status,
                to_status=target_status,
                reason=reason,
                changed_by=changed_by,
                occurred_at=transition_time,
            )
            timestamp = _timestamp(transition_time)
            mention_update = connection.execute(
                f"""
                UPDATE citation_mentions
                SET {status_column} = ?, updated_at = ?, raw_json = ?
                WHERE mention_id = ? AND {status_column} = ? AND updated_at = ?
                """,
                (
                    target_status,
                    timestamp,
                    updated_mention.model_dump_json(exclude_none=False),
                    updated_mention.mention_id,
                    expected_current_status,
                    row["mention_updated_at"],
                ),
            )
            candidate_update = connection.execute(
                f"""
                UPDATE cites_candidates
                SET {status_column} = ?, updated_at = ?, raw_json = ?
                WHERE candidate_id = ? AND {status_column} = ? AND updated_at = ?
                """,
                (
                    target_status,
                    timestamp,
                    updated_candidate.model_dump_json(exclude_none=False),
                    updated_candidate.candidate_id,
                    expected_current_status,
                    row["candidate_updated_at"],
                ),
            )
            if mention_update.rowcount != 1 or candidate_update.rowcount != 1:
                raise CitationStoreConflictError(
                    f"citation {status_column} changed during transition"
                )
            connection.execute(
                """
                INSERT INTO citation_lifecycle_events (
                    event_id, candidate_id, mention_id, project_id, batch_id,
                    axis, from_status, to_status, reason, changed_by,
                    occurred_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.candidate_id,
                    event.mention_id,
                    event.project_id,
                    event.batch_id,
                    event.axis,
                    event.from_status,
                    event.to_status,
                    event.reason,
                    event.changed_by,
                    _timestamp(event.occurred_at),
                    event.model_dump_json(exclude_none=False),
                ),
            )
            connection.commit()
            return CitationLifecycleTransitionResult(
                candidate=updated_candidate,
                mention=updated_mention,
                event=event,
            )
        except (CitationStoreError, KeyError, ValueError):
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise CitationStoreError("citation lifecycle transition failed") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _save_batch_in_transaction(
        self,
        connection: sqlite3.Connection,
        mentions: tuple[CitationMention, ...],
        candidates: tuple[CitesCandidate, ...],
        *,
        batch_id: str,
    ) -> CitationBatchWriteResult:
        canonical_mentions: list[CitationMention] = []
        canonical_candidates: list[CitesCandidate] = []
        created_mentions: list[str] = []
        created_candidates: list[str] = []
        reused_mentions: list[str] = []
        reused_candidates: list[str] = []
        mention_by_input_id: dict[str, CitationMention] = {}

        for mention in mentions:
            canonical, created = self._store_mention(connection, mention)
            mention_by_input_id[mention.mention_id] = canonical
            canonical_mentions.append(canonical)
            (created_mentions if created else reused_mentions).append(canonical.mention_id)

        for candidate in candidates:
            stored_mention = mention_by_input_id.get(candidate.mention_id)
            if stored_mention is None:
                row = connection.execute(
                    "SELECT raw_json FROM citation_mentions WHERE mention_id = ?",
                    (candidate.mention_id,),
                ).fetchone()
                if row is not None:
                    stored_mention = _row_to_mention(row)
            if stored_mention is None:
                raise CitationStoreConflictError(
                    "cites candidate references a citation mention that is not stored"
                )
            canonical_candidate = candidate
            if candidate.mention_id != stored_mention.mention_id:
                canonical_candidate = candidate.model_copy(
                    update={"mention_id": stored_mention.mention_id}
                )
            _require_candidate_matches_mention(canonical_candidate, stored_mention)
            stored, created = self._store_candidate(
                connection,
                canonical_candidate,
            )
            canonical_candidates.append(stored)
            (created_candidates if created else reused_candidates).append(stored.candidate_id)

        return CitationBatchWriteResult(
            batch_id=batch_id,
            mentions=tuple(canonical_mentions),
            candidates=tuple(canonical_candidates),
            created_mention_ids=tuple(created_mentions),
            created_candidate_ids=tuple(created_candidates),
            reused_mention_ids=tuple(reused_mentions),
            reused_candidate_ids=tuple(reused_candidates),
        )

    def _store_mention(
        self,
        connection: sqlite3.Connection,
        mention: CitationMention,
    ) -> tuple[CitationMention, bool]:
        dedupe_hash = citation_mention_dedupe_hash(mention)
        row = connection.execute(
            "SELECT raw_json FROM citation_mentions WHERE dedupe_sha256 = ?",
            (dedupe_hash,),
        ).fetchone()
        if row is not None:
            existing = _row_to_mention(row)
            _require_same_lifecycle(existing, mention, record_kind="citation mention")
            return existing, False
        id_row = connection.execute(
            "SELECT dedupe_sha256 FROM citation_mentions WHERE mention_id = ?",
            (mention.mention_id,),
        ).fetchone()
        if id_row is not None:
            raise CitationStoreConflictError(
                "mention_id is already bound to different citation data"
            )
        connection.execute(
            """
            INSERT INTO citation_mentions (
                mention_id, dedupe_sha256, project_id, batch_id, session_id,
                turn_id, selection_id, source_material_id, outcome,
                target_material_id, review_status, freshness_status,
                created_at, updated_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mention.mention_id,
                dedupe_hash,
                mention.project_id,
                mention.batch_id,
                mention.session_id,
                mention.turn_id,
                mention.selection_id,
                mention.source_material_id,
                mention.outcome,
                mention.target_material_id,
                mention.review_status,
                mention.freshness_status,
                _timestamp(mention.created_at),
                _timestamp(mention.updated_at),
                mention.model_dump_json(exclude_none=False),
            ),
        )
        return mention, True

    def _store_candidate(
        self,
        connection: sqlite3.Connection,
        candidate: CitesCandidate,
    ) -> tuple[CitesCandidate, bool]:
        dedupe_hash = cites_candidate_dedupe_hash(candidate)
        row = connection.execute(
            "SELECT raw_json FROM cites_candidates WHERE dedupe_sha256 = ?",
            (dedupe_hash,),
        ).fetchone()
        if row is not None:
            existing = _row_to_candidate(row)
            _require_same_lifecycle(existing, candidate, record_kind="cites candidate")
            return existing, False
        id_row = connection.execute(
            "SELECT dedupe_sha256 FROM cites_candidates WHERE candidate_id = ?",
            (candidate.candidate_id,),
        ).fetchone()
        if id_row is not None:
            raise CitationStoreConflictError(
                "candidate_id is already bound to different citation data"
            )
        mention_row = connection.execute(
            "SELECT candidate_id FROM cites_candidates WHERE mention_id = ?",
            (candidate.mention_id,),
        ).fetchone()
        if mention_row is not None:
            raise CitationStoreConflictError(
                "citation mention already has a directed cites candidate"
            )
        connection.execute(
            """
            INSERT INTO cites_candidates (
                candidate_id, dedupe_sha256, mention_id, project_id, batch_id,
                session_id, turn_id, selection_id, source_material_id,
                target_material_id, relation, direction, review_status,
                freshness_status, created_at, updated_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.candidate_id,
                dedupe_hash,
                candidate.mention_id,
                candidate.project_id,
                candidate.batch_id,
                candidate.session_id,
                candidate.turn_id,
                candidate.selection_id,
                candidate.source_material_id,
                candidate.target_material_id,
                candidate.relation,
                candidate.direction,
                candidate.review_status,
                candidate.freshness_status,
                _timestamp(candidate.created_at),
                _timestamp(candidate.updated_at),
                candidate.model_dump_json(exclude_none=False),
            ),
        )
        return candidate, True

    def _open(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.DatabaseError:
            pass
        return connection

    def _open_or_raise(self) -> sqlite3.Connection:
        try:
            return self._open()
        except sqlite3.Error as exc:
            raise CitationStoreError("failed to open citation store") from exc

    def _init_schema(self) -> None:
        connection = self._open_or_raise()
        try:
            current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current_version > CITATION_STORE_SCHEMA_VERSION:
                raise CitationStoreError("citation store schema is newer than this runtime")
            with connection:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS citation_mentions (
                        mention_id TEXT PRIMARY KEY,
                        dedupe_sha256 TEXT NOT NULL UNIQUE,
                        project_id TEXT NOT NULL,
                        batch_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        turn_id TEXT NOT NULL,
                        selection_id TEXT,
                        source_material_id TEXT NOT NULL,
                        outcome TEXT NOT NULL CHECK (
                            outcome IN ('matched', 'unmatched', 'ambiguous', 'over_limit', 'failed')
                        ),
                        target_material_id TEXT,
                        review_status TEXT NOT NULL CHECK (
                            review_status IN ('candidate', 'accepted', 'rejected')
                        ),
                        freshness_status TEXT NOT NULL CHECK (
                            freshness_status IN ('fresh', 'stale')
                        ),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        raw_json TEXT NOT NULL
                    )
                    """)
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS cites_candidates (
                        candidate_id TEXT PRIMARY KEY,
                        dedupe_sha256 TEXT NOT NULL UNIQUE,
                        mention_id TEXT NOT NULL UNIQUE,
                        project_id TEXT NOT NULL,
                        batch_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        turn_id TEXT NOT NULL,
                        selection_id TEXT,
                        source_material_id TEXT NOT NULL,
                        target_material_id TEXT NOT NULL,
                        relation TEXT NOT NULL CHECK (relation = 'cites'),
                        direction TEXT NOT NULL CHECK (direction = 'directed'),
                        review_status TEXT NOT NULL CHECK (
                            review_status IN ('candidate', 'accepted', 'rejected')
                        ),
                        freshness_status TEXT NOT NULL CHECK (
                            freshness_status IN ('fresh', 'stale')
                        ),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        raw_json TEXT NOT NULL,
                        FOREIGN KEY (mention_id) REFERENCES citation_mentions(mention_id)
                            ON UPDATE RESTRICT ON DELETE RESTRICT
                    )
                    """)
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS citation_lifecycle_events (
                        event_id TEXT PRIMARY KEY,
                        candidate_id TEXT NOT NULL,
                        mention_id TEXT NOT NULL,
                        project_id TEXT NOT NULL,
                        batch_id TEXT NOT NULL,
                        axis TEXT NOT NULL CHECK (axis IN ('review', 'freshness')),
                        from_status TEXT NOT NULL,
                        to_status TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        changed_by TEXT NOT NULL,
                        occurred_at TEXT NOT NULL,
                        raw_json TEXT NOT NULL,
                        FOREIGN KEY (candidate_id) REFERENCES cites_candidates(candidate_id)
                            ON UPDATE RESTRICT ON DELETE RESTRICT,
                        FOREIGN KEY (mention_id) REFERENCES citation_mentions(mention_id)
                            ON UPDATE RESTRICT ON DELETE RESTRICT
                    )
                    """)
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS citation_capture_receipts (
                        receipt_id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        batch_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        turn_id TEXT NOT NULL,
                        status TEXT NOT NULL CHECK (
                            status IN ('scheduled', 'succeeded', 'failed')
                        ),
                        capture_sha256 TEXT NOT NULL,
                        scheduled_at TEXT NOT NULL,
                        completed_at TEXT,
                        raw_json TEXT NOT NULL,
                        UNIQUE (project_id, batch_id)
                    )
                    """)
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_citation_mentions_turn "
                    "ON citation_mentions(project_id, turn_id, created_at)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_citation_mentions_batch "
                    "ON citation_mentions(project_id, batch_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_citation_mentions_outcome "
                    "ON citation_mentions(project_id, outcome, freshness_status)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_cites_candidates_source "
                    "ON cites_candidates(project_id, source_material_id, created_at)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_cites_candidates_target "
                    "ON cites_candidates(project_id, target_material_id, created_at)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_citation_lifecycle_candidate "
                    "ON citation_lifecycle_events(candidate_id, occurred_at, event_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_citation_lifecycle_project "
                    "ON citation_lifecycle_events(project_id, axis, occurred_at)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_citation_capture_turn "
                    "ON citation_capture_receipts(project_id, session_id, turn_id, scheduled_at)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_citation_capture_status "
                    "ON citation_capture_receipts(project_id, status, scheduled_at)"
                )
                connection.execute(f"PRAGMA user_version = {CITATION_STORE_SCHEMA_VERSION}")
        except CitationStoreError:
            raise
        except sqlite3.Error as exc:
            raise CitationStoreError("failed to initialize citation store") from exc
        finally:
            connection.close()


def citation_capture_sha256(
    *,
    batch_id: str,
    mentions: Sequence[CitationMention],
    candidates: Sequence[CitesCandidate],
) -> str:
    """Hash the exact immutable citation batch scheduled for persistence."""

    normalized_batch = _normalize_id_filter(batch_id, "batch_id")
    mention_records = sorted(
        _validate_mentions(mentions),
        key=lambda item: item.mention_id,
    )
    candidate_records = sorted(
        _validate_candidates(candidates),
        key=lambda item: item.candidate_id,
    )
    if any(record.batch_id != normalized_batch for record in mention_records):
        raise ValueError("citation capture mentions must match batch_id")
    if any(record.batch_id != normalized_batch for record in candidate_records):
        raise ValueError("citation capture candidates must match batch_id")
    payload = {
        "batch_id": normalized_batch,
        "mentions": [item.model_dump(mode="json") for item in mention_records],
        "candidates": [item.model_dump(mode="json") for item in candidate_records],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _capture_count(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < 0 or value > MAX_CITATION_BATCH_RECORDS:
        raise ValueError(
            f"{field_name} must be between 0 and {MAX_CITATION_BATCH_RECORDS}"
        )
    return value


def _row_to_capture_receipt(row: sqlite3.Row) -> CitationCaptureReceipt:
    try:
        return CitationCaptureReceipt.model_validate_json(str(row["raw_json"]))
    except (TypeError, ValidationError, ValueError) as exc:
        raise CitationStoreCorruptionError(
            "citation capture receipt is invalid"
        ) from exc


def _completed_capture_receipt(
    receipt: CitationCaptureReceipt,
    *,
    result: CitationBatchWriteResult | None,
) -> CitationCaptureReceipt:
    payload = receipt.model_dump(mode="python")
    payload.update(
        {
            "status": "succeeded",
            "stored_mention_count": len(result.mentions) if result is not None else 0,
            "stored_candidate_count": len(result.candidates) if result is not None else 0,
            "created_mention_count": (
                len(result.created_mention_ids) if result is not None else 0
            ),
            "created_candidate_count": (
                len(result.created_candidate_ids) if result is not None else 0
            ),
            "reused_mention_count": (
                len(result.reused_mention_ids) if result is not None else 0
            ),
            "reused_candidate_count": (
                len(result.reused_candidate_ids) if result is not None else 0
            ),
            "completed_at": datetime.now(timezone.utc),
        }
    )
    return CitationCaptureReceipt.model_validate(payload)


def _validate_mentions(
    records: Sequence[CitationMention],
) -> tuple[CitationMention, ...]:
    if isinstance(records, (str, bytes)):
        raise TypeError("mentions must be a sequence of CitationMention records")
    normalized = tuple(records)
    if len(normalized) > MAX_CITATION_BATCH_RECORDS:
        raise ValueError(f"mentions accepts at most {MAX_CITATION_BATCH_RECORDS} records")
    if any(not isinstance(record, CitationMention) for record in normalized):
        raise TypeError("mentions must contain only CitationMention records")
    return normalized


def _validate_candidates(
    records: Sequence[CitesCandidate],
) -> tuple[CitesCandidate, ...]:
    if isinstance(records, (str, bytes)):
        raise TypeError("candidates must be a sequence of CitesCandidate records")
    normalized = tuple(records)
    if len(normalized) > MAX_CITATION_BATCH_RECORDS:
        raise ValueError(f"candidates accepts at most {MAX_CITATION_BATCH_RECORDS} records")
    if any(not isinstance(record, CitesCandidate) for record in normalized):
        raise TypeError("candidates must contain only CitesCandidate records")
    return normalized


def _reject_duplicate_input_ids(
    mentions: tuple[CitationMention, ...],
    candidates: tuple[CitesCandidate, ...],
) -> None:
    mention_ids = [record.mention_id for record in mentions]
    candidate_ids = [record.candidate_id for record in candidates]
    if len(set(mention_ids)) != len(mention_ids):
        raise ValueError("save_batch contains duplicate mention_id values")
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("save_batch contains duplicate candidate_id values")


def _require_candidate_matches_mention(
    candidate: CitesCandidate,
    mention: CitationMention,
) -> None:
    if mention.outcome != "matched":
        raise CitationStoreConflictError(
            "cites candidates require a uniquely matched citation mention"
        )
    mention_payload = mention.model_dump(
        mode="json",
        exclude={"schema_version", "mention_id", "created_at", "updated_at"},
    )
    candidate_payload = candidate.model_dump(
        mode="json",
        exclude={
            "schema_version",
            "candidate_id",
            "mention_id",
            "relation",
            "direction",
            "created_at",
            "updated_at",
        },
    )
    if mention_payload != candidate_payload:
        raise CitationStoreConflictError(
            "cites candidate does not match citation mention locator or provenance"
        )


def _require_same_lifecycle(
    existing: CitationMention | CitesCandidate,
    incoming: CitationMention | CitesCandidate,
    *,
    record_kind: str,
) -> None:
    if (
        existing.review_status != incoming.review_status
        or existing.freshness_status != incoming.freshness_status
    ):
        raise CitationStoreConflictError(
            f"{record_kind} lifecycle changes require an explicit transition"
        )


def _row_to_mention(row: sqlite3.Row) -> CitationMention:
    try:
        return CitationMention.model_validate_json(row["raw_json"])
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise CitationStoreCorruptionError("invalid citation mention row") from exc


def _row_to_candidate(row: sqlite3.Row) -> CitesCandidate:
    try:
        return CitesCandidate.model_validate_json(row["raw_json"])
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise CitationStoreCorruptionError("invalid cites candidate row") from exc


def _row_to_lifecycle_event(row: sqlite3.Row) -> CitationLifecycleEvent:
    try:
        return CitationLifecycleEvent.model_validate_json(row["raw_json"])
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise CitationStoreCorruptionError("invalid citation lifecycle event row") from exc


def _lifecycle_pair_from_row(row: sqlite3.Row) -> tuple[CitesCandidate, CitationMention]:
    try:
        candidate = CitesCandidate.model_validate_json(row["candidate_raw_json"])
        mention = CitationMention.model_validate_json(row["mention_raw_json"])
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise CitationStoreCorruptionError("invalid citation lifecycle source rows") from exc
    persisted_values = (
        (candidate.review_status, row["candidate_review_status"], "candidate review_status"),
        (candidate.freshness_status, row["candidate_freshness_status"], "candidate freshness_status"),
        (_timestamp(candidate.updated_at), row["candidate_updated_at"], "candidate updated_at"),
        (mention.review_status, row["mention_review_status"], "mention review_status"),
        (mention.freshness_status, row["mention_freshness_status"], "mention freshness_status"),
        (_timestamp(mention.updated_at), row["mention_updated_at"], "mention updated_at"),
    )
    for model_value, column_value, field_name in persisted_values:
        if model_value != column_value:
            raise CitationStoreCorruptionError(f"{field_name} disagrees with raw_json")
    if candidate.mention_id != mention.mention_id:
        raise CitationStoreCorruptionError("candidate points at the wrong citation mention")
    _require_candidate_matches_mention(candidate, mention)
    return candidate, mention


def _common_filters(
    *,
    project_id: str | None,
    batch_id: str | None,
    session_id: str | None,
    turn_id: str | None,
    review_status: CitationReviewStatus | None,
    freshness_status: CitationFreshnessStatus | None,
) -> tuple[list[str], list[object]]:
    where: list[str] = []
    parameters: list[object] = []
    for column, value in (
        ("project_id", project_id),
        ("batch_id", batch_id),
        ("session_id", session_id),
        ("turn_id", turn_id),
    ):
        if value is not None:
            where.append(f"{column} = ?")
            parameters.append(_normalize_id_filter(value, column))
    if review_status is not None:
        if review_status not in _REVIEW_STATUSES:
            raise ValueError(f"unsupported citation review_status: {review_status!r}")
        where.append("review_status = ?")
        parameters.append(review_status)
    if freshness_status is not None:
        if freshness_status not in _FRESHNESS_STATUSES:
            raise ValueError(f"unsupported citation freshness_status: {freshness_status!r}")
        where.append("freshness_status = ?")
        parameters.append(freshness_status)
    return where, parameters


def _normalize_id_filter(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _ID_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} has an unsupported identifier shape")
    return normalized


def _pagination(limit: int, offset: int) -> tuple[int, int]:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise TypeError("offset must be an integer")
    if limit < 1 or limit > MAX_CITATION_LIST_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_CITATION_LIST_LIMIT}")
    if offset < 0 or offset > 10_000_000:
        raise ValueError("offset must be between 0 and 10000000")
    return limit, offset


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _capture_completion_timestamp(receipt: CitationCaptureReceipt) -> str:
    completed_at = receipt.completed_at
    if completed_at is None:
        raise CitationStoreCorruptionError(
            "terminal citation capture receipt is missing completed_at"
        )
    return _timestamp(completed_at)


def _transition_timestamp(
    value: datetime | None,
    *,
    candidate_updated_at: datetime,
    mention_updated_at: datetime,
) -> datetime:
    latest = max(candidate_updated_at, mention_updated_at).astimezone(timezone.utc)
    if value is None:
        normalized = datetime.now(timezone.utc)
        return normalized if normalized > latest else latest + timedelta(microseconds=1)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("occurred_at must include a timezone")
    normalized = value.astimezone(timezone.utc)
    if normalized <= latest:
        raise ValueError("occurred_at must be later than the current citation updated_at")
    return normalized


__all__ = [
    "CITATION_STORE_SCHEMA_VERSION",
    "CitationBatchWriteResult",
    "CitationCandidateStore",
    "CitationLifecycleEvent",
    "CitationLifecycleTransitionResult",
    "CitationStoreConflictError",
    "CitationStoreCorruptionError",
    "CitationStoreError",
    "citation_capture_sha256",
]
