"""Transactional SQLite ledger for explicitly reviewed graph knowledge."""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from literature_assistant.core.knowledge_graph.reviewed_knowledge_models import (
    AcceptedGraphFact,
    PromoteAcceptedGraphFactRequest,
    ReviewedKnowledgeAvailability,
    ReviewedKnowledgeFreshness,
    ReviewedKnowledgeFreshnessRequest,
    ReviewedKnowledgeMutationResult,
    ReviewedKnowledgeReceipt,
    WithdrawAcceptedGraphFactRequest,
    accepted_graph_fact_content_hash,
    accepted_graph_fact_state_hash,
    reviewed_knowledge_request_hash,
)

REVIEWED_KNOWLEDGE_STORE_SCHEMA_VERSION = 1
MAX_REVIEWED_KNOWLEDGE_LIST_LIMIT = 500

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_ModelT = TypeVar("_ModelT", bound=BaseModel)


class ReviewedKnowledgeStoreError(RuntimeError):
    """Base error for reviewed-knowledge persistence failures."""


class ReviewedKnowledgeConflictError(ReviewedKnowledgeStoreError):
    """Raised when idempotency, state, or compare-and-swap checks fail."""


class ReviewedKnowledgeNotFoundError(ReviewedKnowledgeStoreError):
    """Raised when a project-scoped mutation target does not exist."""


class ReviewedKnowledgeCorruptionError(ReviewedKnowledgeStoreError):
    """Raised when persisted JSON no longer satisfies the strict contract."""


class ReviewedKnowledgeStore:
    """Independent project-scoped ledger for accepted graph facts.

    Every mutation starts with ``BEGIN IMMEDIATE`` and checks both integer
    version and state hash before writing. Operation ids are project-local
    idempotency keys backed by durable request hashes and receipts. This store
    does not import or invoke Wiki, graph projection, candidate, or answer code;
    those surfaces can only consume its bounded reads or explicitly call a
    mutation after their own authorization and candidate-review checks.
    """

    def __init__(self, db_path: str | Path) -> None:
        """Initialize an independent reviewed-knowledge SQLite database.

        Args:
            db_path: Explicit runtime database path owned by the caller.

        Raises:
            ValueError: If the path is empty or names a directory.
            ReviewedKnowledgeStoreError: If schema initialization fails.
        """

        if not str(db_path).strip():
            raise ValueError("db_path must be non-empty")
        resolved = Path(db_path).expanduser().resolve()
        if resolved.exists() and resolved.is_dir():
            raise ValueError("db_path must name a SQLite file")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = resolved
        self._initialize_schema()

    def promote(
        self,
        request: PromoteAcceptedGraphFactRequest,
    ) -> ReviewedKnowledgeMutationResult:
        """Explicitly create or revise one fact from accepted review evidence.

        Candidate acceptance is only an input receipt. Constructing or storing
        candidate review state never calls this method, so acceptance cannot
        implicitly become reviewed knowledge.

        Args:
            request: Validated promotion request, idempotency key, and CAS.

        Returns:
            Committed historical fact revision and durable receipt. Exact
            retries return the original revision with ``replayed=True``.

        Raises:
            TypeError: If ``request`` is not the strict promotion model.
            ReviewedKnowledgeConflictError: If idempotency or CAS differs.
            ReviewedKnowledgeStoreError: If SQLite rejects the transaction.
        """

        if not isinstance(request, PromoteAcceptedGraphFactRequest):
            raise TypeError("request must be PromoteAcceptedGraphFactRequest")
        request_hash = reviewed_knowledge_request_hash(request)
        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._load_replay(
                connection,
                project_id=request.project_id,
                operation_id=request.operation_id,
                request_hash=request_hash,
            )
            if replay is not None:
                connection.commit()
                return replay

            current = self._fetch_fact(
                connection,
                project_id=request.project_id,
                fact_id=request.fact_id,
            )
            self._require_promotion_cas(request=request, current=current)
            if current is not None and current.availability_status == "withdrawn":
                raise ReviewedKnowledgeConflictError(
                    "withdrawn facts cannot be revised without an explicit restore contract"
                )

            previous_version = current.version if current is not None else 0
            previous_hash = current.state_sha256 if current is not None else None
            version = previous_version + 1
            content_hash = accepted_graph_fact_content_hash(
                project_id=request.project_id,
                fact_id=request.fact_id,
                subject_ref=request.subject_ref,
                predicate=request.predicate,
                object_ref=request.object_ref,
                statement=request.statement,
                provenance=request.provenance,
            )
            state_hash = accepted_graph_fact_state_hash(
                project_id=request.project_id,
                fact_id=request.fact_id,
                version=version,
                freshness_status="fresh",
                availability_status="active",
                content_sha256=content_hash,
                accepted_review=request.accepted_review,
                stale_source_revision=None,
            )
            fact = AcceptedGraphFact(
                project_id=request.project_id,
                fact_id=request.fact_id,
                subject_ref=request.subject_ref,
                predicate=request.predicate,
                object_ref=request.object_ref,
                statement=request.statement,
                provenance=request.provenance,
                accepted_review=request.accepted_review,
                freshness_status="fresh",
                availability_status="active",
                stale_source_revision=None,
                version=version,
                content_sha256=content_hash,
                state_sha256=state_hash,
                created_at=(
                    current.created_at if current is not None else request.requested_at
                ),
                updated_at=request.requested_at,
            )
            receipt = ReviewedKnowledgeReceipt(
                receipt_id=f"reviewed-knowledge-{uuid4().hex}",
                operation_id=request.operation_id,
                request_sha256=request_hash,
                project_id=request.project_id,
                fact_id=request.fact_id,
                operation="promote",
                outcome="created" if current is None else "revised",
                previous_version=previous_version,
                result_version=version,
                previous_state_sha256=previous_hash,
                result_state_sha256=fact.state_sha256,
                accepted_review=request.accepted_review,
                reason=request.reason,
                changed_by=request.requested_by,
                occurred_at=request.requested_at,
            )
            self._commit_mutation(
                connection,
                current=current,
                fact=fact,
                receipt=receipt,
            )
            connection.commit()
            return ReviewedKnowledgeMutationResult(
                fact=fact, receipt=receipt, replayed=False
            )
        except ReviewedKnowledgeStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise ReviewedKnowledgeStoreError(
                "reviewed-knowledge promotion failed"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def transition_freshness(
        self,
        request: ReviewedKnowledgeFreshnessRequest,
    ) -> ReviewedKnowledgeMutationResult:
        """Mark one active fact stale or explicitly revalidate it.

        Args:
            request: Source-revision evidence and exact current-state CAS.

        Returns:
            Committed historical fact revision and durable receipt.

        Raises:
            ReviewedKnowledgeNotFoundError: If the project-scoped fact is absent.
            ReviewedKnowledgeConflictError: If the state or evidence is stale.
            ReviewedKnowledgeStoreError: If SQLite rejects the transaction.
        """

        if not isinstance(request, ReviewedKnowledgeFreshnessRequest):
            raise TypeError("request must be ReviewedKnowledgeFreshnessRequest")
        request_hash = reviewed_knowledge_request_hash(request)
        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._load_replay(
                connection,
                project_id=request.project_id,
                operation_id=request.operation_id,
                request_hash=request_hash,
            )
            if replay is not None:
                connection.commit()
                return replay

            current = self._require_current_fact(
                connection,
                project_id=request.project_id,
                fact_id=request.fact_id,
            )
            self._require_existing_cas(
                current=current,
                expected_version=request.expected_version,
                expected_state_hash=request.expected_state_sha256,
                occurred_at=request.occurred_at,
            )
            if current.availability_status != "active":
                raise ReviewedKnowledgeConflictError(
                    "withdrawn facts cannot change freshness"
                )

            if request.operation == "mark_stale":
                fact = self._build_stale_fact(current=current, request=request)
                outcome: Literal["stale", "revalidated"] = "stale"
            else:
                fact = self._build_revalidated_fact(current=current, request=request)
                outcome = "revalidated"

            receipt = ReviewedKnowledgeReceipt(
                receipt_id=f"reviewed-knowledge-{uuid4().hex}",
                operation_id=request.operation_id,
                request_sha256=request_hash,
                project_id=request.project_id,
                fact_id=request.fact_id,
                operation=request.operation,
                outcome=outcome,
                previous_version=current.version,
                result_version=fact.version,
                previous_state_sha256=current.state_sha256,
                result_state_sha256=fact.state_sha256,
                observed_source_revision=request.observed_source_revision,
                validated_provenance=request.validated_provenance,
                reason=request.reason,
                changed_by=request.changed_by,
                occurred_at=request.occurred_at,
            )
            self._commit_mutation(
                connection,
                current=current,
                fact=fact,
                receipt=receipt,
            )
            connection.commit()
            return ReviewedKnowledgeMutationResult(
                fact=fact, receipt=receipt, replayed=False
            )
        except ReviewedKnowledgeStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise ReviewedKnowledgeStoreError(
                "reviewed-knowledge freshness transition failed"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def withdraw(
        self,
        request: WithdrawAcceptedGraphFactRequest,
    ) -> ReviewedKnowledgeMutationResult:
        """Explicitly withdraw an active fact while retaining its audit history."""

        if not isinstance(request, WithdrawAcceptedGraphFactRequest):
            raise TypeError("request must be WithdrawAcceptedGraphFactRequest")
        request_hash = reviewed_knowledge_request_hash(request)
        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._load_replay(
                connection,
                project_id=request.project_id,
                operation_id=request.operation_id,
                request_hash=request_hash,
            )
            if replay is not None:
                connection.commit()
                return replay

            current = self._require_current_fact(
                connection,
                project_id=request.project_id,
                fact_id=request.fact_id,
            )
            self._require_existing_cas(
                current=current,
                expected_version=request.expected_version,
                expected_state_hash=request.expected_state_sha256,
                occurred_at=request.occurred_at,
            )
            if current.availability_status != "active":
                raise ReviewedKnowledgeConflictError("fact is already withdrawn")
            version = current.version + 1
            state_hash = accepted_graph_fact_state_hash(
                project_id=current.project_id,
                fact_id=current.fact_id,
                version=version,
                freshness_status=current.freshness_status,
                availability_status="withdrawn",
                content_sha256=current.content_sha256,
                accepted_review=current.accepted_review,
                stale_source_revision=current.stale_source_revision,
            )
            fact = current.model_copy(
                update={
                    "availability_status": "withdrawn",
                    "version": version,
                    "state_sha256": state_hash,
                    "updated_at": request.occurred_at,
                }
            )
            fact = AcceptedGraphFact.model_validate(fact.model_dump(mode="python"))
            receipt = ReviewedKnowledgeReceipt(
                receipt_id=f"reviewed-knowledge-{uuid4().hex}",
                operation_id=request.operation_id,
                request_sha256=request_hash,
                project_id=request.project_id,
                fact_id=request.fact_id,
                operation="withdraw",
                outcome="withdrawn",
                previous_version=current.version,
                result_version=fact.version,
                previous_state_sha256=current.state_sha256,
                result_state_sha256=fact.state_sha256,
                reason=request.reason,
                changed_by=request.changed_by,
                occurred_at=request.occurred_at,
            )
            self._commit_mutation(
                connection,
                current=current,
                fact=fact,
                receipt=receipt,
            )
            connection.commit()
            return ReviewedKnowledgeMutationResult(
                fact=fact, receipt=receipt, replayed=False
            )
        except ReviewedKnowledgeStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise ReviewedKnowledgeStoreError(
                "reviewed-knowledge withdrawal failed"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_fact(self, *, project_id: str, fact_id: str) -> AcceptedGraphFact | None:
        """Return one fact only when both project and fact identity match."""

        normalized_project = _normalize_identifier(project_id, "project_id")
        normalized_fact = _normalize_identifier(fact_id, "fact_id")
        with closing(self._open_or_raise()) as connection:
            return self._fetch_fact(
                connection,
                project_id=normalized_project,
                fact_id=normalized_fact,
            )

    def list_facts(
        self,
        *,
        project_id: str,
        freshness_status: ReviewedKnowledgeFreshness | None = None,
        availability_status: ReviewedKnowledgeAvailability | None = "active",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[AcceptedGraphFact, ...]:
        """Return a bounded project-isolated current-fact page.

        ``availability_status`` defaults to ``active`` so Wiki and graph
        consumers cannot accidentally project withdrawn facts. Pass ``None``
        only in explicit audit views.
        """

        normalized_project = _normalize_identifier(project_id, "project_id")
        bounded_limit = _validate_limit(limit)
        bounded_offset = _validate_offset(offset)
        if freshness_status not in {None, "fresh", "stale"}:
            raise ValueError("freshness_status must be fresh, stale, or None")
        if availability_status not in {None, "active", "withdrawn"}:
            raise ValueError("availability_status must be active, withdrawn, or None")
        query = "SELECT raw_json FROM accepted_graph_facts WHERE project_id = ?"
        parameters: list[object] = [normalized_project]
        if freshness_status is not None:
            query += " AND freshness_status = ?"
            parameters.append(freshness_status)
        if availability_status is not None:
            query += " AND availability_status = ?"
            parameters.append(availability_status)
        query += " ORDER BY updated_at DESC, fact_id ASC LIMIT ? OFFSET ?"
        parameters.extend((bounded_limit, bounded_offset))
        with closing(self._open_or_raise()) as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return tuple(
            self._load_model(row["raw_json"], AcceptedGraphFact, "accepted graph fact")
            for row in rows
        )

    def list_fact_revisions(
        self,
        *,
        project_id: str,
        fact_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[AcceptedGraphFact, ...]:
        """Return a bounded newest-first audit history for one project fact."""

        normalized_project = _normalize_identifier(project_id, "project_id")
        normalized_fact = _normalize_identifier(fact_id, "fact_id")
        bounded_limit = _validate_limit(limit)
        bounded_offset = _validate_offset(offset)
        with closing(self._open_or_raise()) as connection:
            rows = connection.execute(
                """
                SELECT raw_json
                FROM accepted_graph_fact_revisions
                WHERE project_id = ? AND fact_id = ?
                ORDER BY version DESC
                LIMIT ? OFFSET ?
                """,
                (normalized_project, normalized_fact, bounded_limit, bounded_offset),
            ).fetchall()
        return tuple(
            self._load_model(row["raw_json"], AcceptedGraphFact, "fact revision")
            for row in rows
        )

    def get_receipt(
        self,
        *,
        project_id: str,
        operation_id: str,
    ) -> ReviewedKnowledgeReceipt | None:
        """Return one durable receipt within its owning project."""

        normalized_project = _normalize_identifier(project_id, "project_id")
        normalized_operation = _normalize_identifier(operation_id, "operation_id")
        with closing(self._open_or_raise()) as connection:
            row = connection.execute(
                """
                SELECT raw_json
                FROM reviewed_knowledge_receipts
                WHERE project_id = ? AND operation_id = ?
                """,
                (normalized_project, normalized_operation),
            ).fetchone()
        if row is None:
            return None
        return self._load_model(row["raw_json"], ReviewedKnowledgeReceipt, "receipt")

    def list_receipts(
        self,
        *,
        project_id: str,
        fact_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[ReviewedKnowledgeReceipt, ...]:
        """Return a bounded project-isolated mutation receipt page."""

        normalized_project = _normalize_identifier(project_id, "project_id")
        normalized_fact = (
            _normalize_identifier(fact_id, "fact_id") if fact_id is not None else None
        )
        bounded_limit = _validate_limit(limit)
        bounded_offset = _validate_offset(offset)
        query = "SELECT raw_json FROM reviewed_knowledge_receipts WHERE project_id = ?"
        parameters: list[object] = [normalized_project]
        if normalized_fact is not None:
            query += " AND fact_id = ?"
            parameters.append(normalized_fact)
        query += " ORDER BY occurred_at DESC, receipt_id ASC LIMIT ? OFFSET ?"
        parameters.extend((bounded_limit, bounded_offset))
        with closing(self._open_or_raise()) as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return tuple(
            self._load_model(row["raw_json"], ReviewedKnowledgeReceipt, "receipt")
            for row in rows
        )

    def _build_stale_fact(
        self,
        *,
        current: AcceptedGraphFact,
        request: ReviewedKnowledgeFreshnessRequest,
    ) -> AcceptedGraphFact:
        if current.freshness_status != "fresh":
            raise ReviewedKnowledgeConflictError("only fresh facts can be marked stale")
        observed = request.observed_source_revision
        if observed is None:
            raise ValueError("mark_stale requires observed source revision")
        matching_locator = tuple(
            item
            for item in current.provenance
            if (item.material_id, item.locator)
            == (observed.material_id, observed.locator)
        )
        if not matching_locator:
            raise ReviewedKnowledgeConflictError(
                "observed source material locator is not part of the fact provenance"
            )
        if matching_locator[0].identity_tuple() == observed.identity_tuple():
            raise ReviewedKnowledgeConflictError(
                "observed source revision does not differ from persisted provenance"
            )
        version = current.version + 1
        state_hash = accepted_graph_fact_state_hash(
            project_id=current.project_id,
            fact_id=current.fact_id,
            version=version,
            freshness_status="stale",
            availability_status=current.availability_status,
            content_sha256=current.content_sha256,
            accepted_review=current.accepted_review,
            stale_source_revision=observed,
        )
        updated = current.model_copy(
            update={
                "freshness_status": "stale",
                "stale_source_revision": observed,
                "version": version,
                "state_sha256": state_hash,
                "updated_at": request.occurred_at,
            }
        )
        return AcceptedGraphFact.model_validate(updated.model_dump(mode="python"))

    def _build_revalidated_fact(
        self,
        *,
        current: AcceptedGraphFact,
        request: ReviewedKnowledgeFreshnessRequest,
    ) -> AcceptedGraphFact:
        if current.freshness_status != "stale" or current.stale_source_revision is None:
            raise ReviewedKnowledgeConflictError("only stale facts can be revalidated")
        current_locators = {
            (item.material_id, item.locator) for item in current.provenance
        }
        validated_locators = {
            (item.material_id, item.locator) for item in request.validated_provenance
        }
        if current_locators != validated_locators:
            raise ReviewedKnowledgeConflictError(
                "revalidation must preserve the complete provenance locator set"
            )
        stale_identity = current.stale_source_revision.identity_tuple()
        stale_locator = (
            current.stale_source_revision.material_id,
            current.stale_source_revision.locator,
        )
        if not any(
            (item.material_id, item.locator) == stale_locator
            and item.identity_tuple() == stale_identity
            for item in request.validated_provenance
        ):
            raise ReviewedKnowledgeConflictError(
                "revalidation must confirm the source revision that marked the fact stale"
            )
        version = current.version + 1
        content_hash = accepted_graph_fact_content_hash(
            project_id=current.project_id,
            fact_id=current.fact_id,
            subject_ref=current.subject_ref,
            predicate=current.predicate,
            object_ref=current.object_ref,
            statement=current.statement,
            provenance=request.validated_provenance,
        )
        state_hash = accepted_graph_fact_state_hash(
            project_id=current.project_id,
            fact_id=current.fact_id,
            version=version,
            freshness_status="fresh",
            availability_status=current.availability_status,
            content_sha256=content_hash,
            accepted_review=current.accepted_review,
            stale_source_revision=None,
        )
        updated = current.model_copy(
            update={
                "provenance": request.validated_provenance,
                "freshness_status": "fresh",
                "stale_source_revision": None,
                "version": version,
                "content_sha256": content_hash,
                "state_sha256": state_hash,
                "updated_at": request.occurred_at,
            }
        )
        return AcceptedGraphFact.model_validate(updated.model_dump(mode="python"))

    @staticmethod
    def _require_promotion_cas(
        *,
        request: PromoteAcceptedGraphFactRequest,
        current: AcceptedGraphFact | None,
    ) -> None:
        if current is None:
            if request.expected_version != 0:
                raise ReviewedKnowledgeConflictError(
                    "fact does not exist at the expected version"
                )
            return
        if request.expected_version == 0:
            raise ReviewedKnowledgeConflictError("fact already exists")
        ReviewedKnowledgeStore._require_existing_cas(
            current=current,
            expected_version=request.expected_version,
            expected_state_hash=request.expected_state_sha256 or "",
            occurred_at=request.requested_at,
        )

    @staticmethod
    def _require_existing_cas(
        *,
        current: AcceptedGraphFact,
        expected_version: int,
        expected_state_hash: str,
        occurred_at: object,
    ) -> None:
        if (
            current.version != expected_version
            or current.state_sha256 != expected_state_hash
        ):
            raise ReviewedKnowledgeConflictError(
                "fact version or state hash no longer matches the request"
            )
        if not hasattr(occurred_at, "__lt__"):
            raise TypeError("mutation timestamp is invalid")
        if occurred_at < current.updated_at:  # type: ignore[operator]
            raise ReviewedKnowledgeConflictError(
                "mutation timestamp cannot precede the current fact revision"
            )

    def _commit_mutation(
        self,
        connection: sqlite3.Connection,
        *,
        current: AcceptedGraphFact | None,
        fact: AcceptedGraphFact,
        receipt: ReviewedKnowledgeReceipt,
    ) -> None:
        raw_fact = fact.model_dump_json()
        if current is None:
            connection.execute(
                """
                INSERT INTO accepted_graph_facts(
                    project_id, fact_id, freshness_status, availability_status,
                    version, state_sha256, updated_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact.project_id,
                    fact.fact_id,
                    fact.freshness_status,
                    fact.availability_status,
                    fact.version,
                    fact.state_sha256,
                    fact.updated_at.isoformat(),
                    raw_fact,
                ),
            )
        else:
            cursor = connection.execute(
                """
                UPDATE accepted_graph_facts
                SET freshness_status = ?, availability_status = ?, version = ?,
                    state_sha256 = ?, updated_at = ?, raw_json = ?
                WHERE project_id = ? AND fact_id = ?
                  AND version = ? AND state_sha256 = ?
                """,
                (
                    fact.freshness_status,
                    fact.availability_status,
                    fact.version,
                    fact.state_sha256,
                    fact.updated_at.isoformat(),
                    raw_fact,
                    fact.project_id,
                    fact.fact_id,
                    current.version,
                    current.state_sha256,
                ),
            )
            if cursor.rowcount != 1:
                raise ReviewedKnowledgeConflictError(
                    "fact changed before the mutation could be committed"
                )
        connection.execute(
            """
            INSERT INTO accepted_graph_fact_revisions(
                project_id, fact_id, version, state_sha256, updated_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                fact.project_id,
                fact.fact_id,
                fact.version,
                fact.state_sha256,
                fact.updated_at.isoformat(),
                raw_fact,
            ),
        )
        connection.execute(
            """
            INSERT INTO reviewed_knowledge_receipts(
                project_id, operation_id, receipt_id, fact_id, operation,
                request_sha256, occurred_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt.project_id,
                receipt.operation_id,
                receipt.receipt_id,
                receipt.fact_id,
                receipt.operation,
                receipt.request_sha256,
                receipt.occurred_at.isoformat(),
                receipt.model_dump_json(),
            ),
        )

    def _load_replay(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        operation_id: str,
        request_hash: str,
    ) -> ReviewedKnowledgeMutationResult | None:
        row = connection.execute(
            """
            SELECT request_sha256, raw_json
            FROM reviewed_knowledge_receipts
            WHERE project_id = ? AND operation_id = ?
            """,
            (project_id, operation_id),
        ).fetchone()
        if row is None:
            return None
        if row["request_sha256"] != request_hash:
            raise ReviewedKnowledgeConflictError(
                "operation_id was already used for a different request"
            )
        receipt = self._load_model(
            row["raw_json"],
            ReviewedKnowledgeReceipt,
            "receipt",
        )
        fact = self._fetch_revision(
            connection,
            project_id=receipt.project_id,
            fact_id=receipt.fact_id,
            version=receipt.result_version,
        )
        if fact is None or fact.state_sha256 != receipt.result_state_sha256:
            raise ReviewedKnowledgeCorruptionError(
                "receipt result revision is missing or inconsistent"
            )
        return ReviewedKnowledgeMutationResult(
            fact=fact, receipt=receipt, replayed=True
        )

    def _require_current_fact(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        fact_id: str,
    ) -> AcceptedGraphFact:
        fact = self._fetch_fact(connection, project_id=project_id, fact_id=fact_id)
        if fact is None:
            raise ReviewedKnowledgeNotFoundError("accepted graph fact was not found")
        return fact

    def _fetch_fact(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        fact_id: str,
    ) -> AcceptedGraphFact | None:
        row = connection.execute(
            """
            SELECT raw_json
            FROM accepted_graph_facts
            WHERE project_id = ? AND fact_id = ?
            """,
            (project_id, fact_id),
        ).fetchone()
        if row is None:
            return None
        return self._load_model(
            row["raw_json"], AcceptedGraphFact, "accepted graph fact"
        )

    def _fetch_revision(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        fact_id: str,
        version: int,
    ) -> AcceptedGraphFact | None:
        row = connection.execute(
            """
            SELECT raw_json
            FROM accepted_graph_fact_revisions
            WHERE project_id = ? AND fact_id = ? AND version = ?
            """,
            (project_id, fact_id, version),
        ).fetchone()
        if row is None:
            return None
        return self._load_model(row["raw_json"], AcceptedGraphFact, "fact revision")

    @staticmethod
    def _load_model(raw_json: str, model: type[_ModelT], label: str) -> _ModelT:
        try:
            return model.model_validate_json(raw_json)
        except (TypeError, ValidationError, ValueError) as exc:
            raise ReviewedKnowledgeCorruptionError(
                f"persisted {label} is invalid"
            ) from exc

    def _initialize_schema(self) -> None:
        connection = self._open_or_raise(initialize=True)
        try:
            current_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if current_version not in {0, REVIEWED_KNOWLEDGE_STORE_SCHEMA_VERSION}:
                raise ReviewedKnowledgeStoreError(
                    "reviewed-knowledge store schema version is unsupported"
                )
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS accepted_graph_facts (
                    project_id TEXT NOT NULL,
                    fact_id TEXT NOT NULL,
                    freshness_status TEXT NOT NULL
                        CHECK(freshness_status IN ('fresh', 'stale')),
                    availability_status TEXT NOT NULL
                        CHECK(availability_status IN ('active', 'withdrawn')),
                    version INTEGER NOT NULL CHECK(version >= 1),
                    state_sha256 TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    PRIMARY KEY(project_id, fact_id)
                )
                """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS accepted_graph_fact_revisions (
                    project_id TEXT NOT NULL,
                    fact_id TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK(version >= 1),
                    state_sha256 TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    PRIMARY KEY(project_id, fact_id, version),
                    FOREIGN KEY(project_id, fact_id)
                        REFERENCES accepted_graph_facts(project_id, fact_id)
                        ON DELETE RESTRICT
                )
                """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS reviewed_knowledge_receipts (
                    project_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    receipt_id TEXT NOT NULL UNIQUE,
                    fact_id TEXT NOT NULL,
                    operation TEXT NOT NULL
                        CHECK(operation IN ('promote', 'mark_stale', 'revalidate', 'withdraw')),
                    request_sha256 TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    PRIMARY KEY(project_id, operation_id),
                    FOREIGN KEY(project_id, fact_id)
                        REFERENCES accepted_graph_facts(project_id, fact_id)
                        ON DELETE RESTRICT
                )
                """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_reviewed_facts_project_status
                ON accepted_graph_facts(
                    project_id, availability_status, freshness_status, updated_at
                )
                """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_reviewed_receipts_project_fact
                ON reviewed_knowledge_receipts(project_id, fact_id, occurred_at)
                """)
            connection.execute(
                f"PRAGMA user_version = {REVIEWED_KNOWLEDGE_STORE_SCHEMA_VERSION}"
            )
            connection.commit()
        except ReviewedKnowledgeStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise ReviewedKnowledgeStoreError(
                "failed to initialize reviewed-knowledge store"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _open_or_raise(self, *, initialize: bool = False) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(
                self.db_path, timeout=5.0, isolation_level=None
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            return connection
        except sqlite3.Error as exc:
            action = "initialize" if initialize else "open"
            raise ReviewedKnowledgeStoreError(
                f"unable to {action} reviewed-knowledge store"
            ) from exc


def _normalize_identifier(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not _ID_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} has an unsupported identifier shape")
    return normalized


def _validate_limit(limit: int) -> int:
    if isinstance(limit, bool):
        raise ValueError("limit must be an integer")
    bounded = int(limit)
    if bounded != limit or bounded < 1 or bounded > MAX_REVIEWED_KNOWLEDGE_LIST_LIMIT:
        raise ValueError(
            f"limit must be between 1 and {MAX_REVIEWED_KNOWLEDGE_LIST_LIMIT}"
        )
    return bounded


def _validate_offset(offset: int) -> int:
    if isinstance(offset, bool):
        raise ValueError("offset must be an integer")
    bounded = int(offset)
    if bounded != offset or bounded < 0:
        raise ValueError("offset must be a non-negative integer")
    return bounded


__all__ = [
    "MAX_REVIEWED_KNOWLEDGE_LIST_LIMIT",
    "REVIEWED_KNOWLEDGE_STORE_SCHEMA_VERSION",
    "ReviewedKnowledgeConflictError",
    "ReviewedKnowledgeCorruptionError",
    "ReviewedKnowledgeNotFoundError",
    "ReviewedKnowledgeStore",
    "ReviewedKnowledgeStoreError",
]
