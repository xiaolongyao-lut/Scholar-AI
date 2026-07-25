"""Transactional SQLite persistence for literature acquisition state."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Sequence
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import TypeVar, cast

from pydantic import BaseModel, ValidationError

from .models import (
    AcquisitionAttempt,
    AcquisitionAttemptOutcome,
    AcquisitionAttemptStage,
    ArtifactPromotionProof,
    ArtifactPromotionState,
    CandidateManifest,
    CandidateVersionRelation,
    DownloadJob,
    DownloadJobStatus,
    GateStatus,
    HumanAccessGate,
    IdentityMergeReceipt,
    ImportPublicationState,
    ImportReceipt,
    ImportStatus,
    SearchRun,
    ValidatedArtifact,
    build_explicit_version_relation,
    semantic_digest,
    utc_now,
)


ACQUISITION_STORE_SCHEMA_VERSION = 3
MAX_LIST_LIMIT = 500
_TERMINAL_DOWNLOAD_OUTCOMES = {
    DownloadJobStatus.PAUSED: AcquisitionAttemptOutcome.PAUSED,
    DownloadJobStatus.HUMAN_REQUIRED: AcquisitionAttemptOutcome.HUMAN_REQUIRED,
    DownloadJobStatus.COMPLETED: AcquisitionAttemptOutcome.SUCCEEDED,
    DownloadJobStatus.FAILED: AcquisitionAttemptOutcome.FAILED,
    DownloadJobStatus.CANCELLED: AcquisitionAttemptOutcome.CANCELLED,
}
_SETTLED_DOWNLOAD_OUTCOMES = frozenset(
    status for status in _TERMINAL_DOWNLOAD_OUTCOMES if status is not DownloadJobStatus.COMPLETED
)


class AcquisitionStoreError(RuntimeError):
    """Base error for acquisition persistence failures."""


class AcquisitionStoreConflictError(AcquisitionStoreError):
    """Raised when a caller loses a version compare-and-swap."""


class AcquisitionStoreCorruptionError(AcquisitionStoreError):
    """Raised when durable JSON no longer satisfies its strict contract."""


_RecordT = TypeVar("_RecordT", bound=BaseModel)


class AcquisitionStore:
    """SQLite-backed durable state for one or more project acquisition runs.

    A fresh connection is opened for every public operation. Mutations use
    ``BEGIN IMMEDIATE`` and integer versions so concurrent desktop/MCP callers
    cannot silently overwrite each other. Opening the store never launches a
    network worker; callers explicitly invoke ``recover_interrupted_jobs`` and
    then decide when to resume queued work.
    """

    def __init__(self, db_path: str | Path) -> None:
        """Initialize the acquisition store at an explicit SQLite path.

        Args:
            db_path: Runtime-state database path owned by the caller.

        Raises:
            ValueError: If the path is empty or names a directory.
            AcquisitionStoreError: If the schema cannot be initialized.
        """

        if not str(db_path).strip():
            raise ValueError("db_path must be non-empty")
        resolved = Path(db_path).expanduser().resolve()
        if resolved.exists() and resolved.is_dir():
            raise ValueError("db_path must name a SQLite file")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = resolved
        self._initialize_schema()

    def save_search_run(
        self,
        run: SearchRun,
        *,
        expected_version: int | None = None,
        identity_receipts: Sequence[IdentityMergeReceipt] = (),
        version_relations: Sequence[CandidateVersionRelation] = (),
    ) -> SearchRun:
        """Atomically persist a run, candidates, identity decisions, and versions.

        Args:
            run: Fully validated run, including its bounded candidates.
            expected_version: Existing version required for a replacement.
                Omit only for an idempotent create.
            identity_receipts: Complete bounded-audit ledger for this run state.
            version_relations: Complete explicit version-edge ledger for this run.

        Returns:
            Canonical persisted run.

        Raises:
            AcquisitionStoreConflictError: If identity/version state differs.
            AcquisitionStoreError: If SQLite rejects the transaction.
        """

        if not isinstance(run, SearchRun):
            raise TypeError("run must be SearchRun")
        receipts = tuple(identity_receipts)
        relations = tuple(version_relations)
        self._validate_search_run_ledgers(run, receipts, relations)
        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            stored = self._save_versioned_record(
                connection,
                table="search_runs",
                id_column="run_id",
                record_id=run.run_id,
                project_id=run.query.project_id,
                status=run.status.value,
                record=run,
                expected_version=expected_version,
            )
            if stored is run or expected_version is not None:
                self._replace_search_run_children(connection, run, receipts, relations)
            else:
                self._assert_search_run_children_match(connection, run, receipts, relations)
            connection.commit()
            return self._load_model(stored.model_dump_json(), SearchRun, "search run")
        except AcquisitionStoreError:
            connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise AcquisitionStoreConflictError("search run child records conflict") from exc
        except sqlite3.Error as exc:
            connection.rollback()
            raise AcquisitionStoreError("search run transaction failed") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_search_run(self, run_id: str) -> SearchRun | None:
        """Return one strict search run by id."""

        return self._get_record("search_runs", "run_id", run_id, SearchRun, "search run")

    def get_candidate(self, candidate_id: str) -> CandidateManifest | None:
        """Return one strict candidate manifest by id."""

        return self._get_record(
            "candidates",
            "candidate_id",
            candidate_id,
            CandidateManifest,
            "candidate",
        )

    def list_identity_merge_receipts(
        self,
        run_id: str,
        *,
        limit: int = 100,
    ) -> tuple[IdentityMergeReceipt, ...]:
        """Return a bounded, stable-order identity-decision ledger for one run."""

        normalized_run_id = _normalize_identifier(run_id, "run_id")
        bounded_limit = _validate_limit(limit)
        with closing(self._open_or_raise()) as connection:
            rows = connection.execute(
                "SELECT raw_json FROM identity_merge_receipts WHERE run_id = ? "
                "ORDER BY created_at ASC, merge_id ASC LIMIT ?",
                (normalized_run_id, bounded_limit),
            ).fetchall()
        return tuple(
            self._load_model(row["raw_json"], IdentityMergeReceipt, "identity merge receipt")
            for row in rows
        )

    def list_candidate_version_relations(
        self,
        run_id: str,
        *,
        limit: int = 100,
    ) -> tuple[CandidateVersionRelation, ...]:
        """Return bounded explicit version relations for one search run."""

        normalized_run_id = _normalize_identifier(run_id, "run_id")
        bounded_limit = _validate_limit(limit)
        with closing(self._open_or_raise()) as connection:
            rows = connection.execute(
                "SELECT raw_json FROM candidate_version_relations WHERE run_id = ? "
                "ORDER BY created_at ASC, relation_id ASC LIMIT ?",
                (normalized_run_id, bounded_limit),
            ).fetchall()
        return tuple(
            self._load_model(row["raw_json"], CandidateVersionRelation, "candidate version relation")
            for row in rows
        )

    def append_acquisition_attempt(self, attempt: AcquisitionAttempt) -> AcquisitionAttempt:
        """Insert one immutable acquisition attempt, allowing exact idempotent replay.

        Args:
            attempt: Strict run- or job-owned audit record.

        Returns:
            The canonical stored attempt.

        Raises:
            AcquisitionStoreConflictError: If the stable id or owner ordinal is
                reused for different facts.
        """

        if not isinstance(attempt, AcquisitionAttempt):
            raise TypeError("attempt must be AcquisitionAttempt")
        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            stored = self._insert_acquisition_attempt(connection, attempt)
            connection.commit()
            return stored
        except AcquisitionStoreError:
            connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise AcquisitionStoreConflictError(
                "acquisition attempt conflicts with existing audit state"
            ) from exc
        except sqlite3.Error as exc:
            connection.rollback()
            raise AcquisitionStoreError("acquisition attempt transaction failed") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_acquisition_attempt(self, attempt_id: str) -> AcquisitionAttempt | None:
        """Return one immutable acquisition attempt by its stable id."""

        normalized = _normalize_identifier(attempt_id, "attempt_id")
        with closing(self._open_or_raise()) as connection:
            row = connection.execute(
                "SELECT raw_json FROM acquisition_attempts WHERE attempt_id = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        return self._load_model(
            row["raw_json"],
            AcquisitionAttempt,
            "acquisition attempt",
        )

    def list_acquisition_attempts(
        self,
        *,
        run_id: str | None = None,
        job_id: str | None = None,
        limit: int = 100,
    ) -> tuple[AcquisitionAttempt, ...]:
        """Return stable-order append-only attempts for exactly one owner."""

        if (run_id is None) == (job_id is None):
            raise ValueError("exactly one run_id or job_id is required")
        owner_column = "run_id" if run_id is not None else "job_id"
        owner_id = _normalize_identifier(run_id or job_id or "", owner_column)
        bounded_limit = _validate_limit(limit)
        with closing(self._open_or_raise()) as connection:
            rows = connection.execute(
                f"SELECT raw_json FROM acquisition_attempts WHERE {owner_column} = ? "
                "ORDER BY ordinal ASC, started_at ASC, attempt_id ASC LIMIT ?",
                (owner_id, bounded_limit),
            ).fetchall()
        return tuple(
            self._load_model(row["raw_json"], AcquisitionAttempt, "acquisition attempt")
            for row in rows
        )

    def save_download_job(
        self,
        job: DownloadJob,
        *,
        expected_version: int | None = None,
    ) -> DownloadJob:
        """Create or CAS-replace one download job."""

        if not isinstance(job, DownloadJob):
            raise TypeError("job must be DownloadJob")
        return cast(
            DownloadJob,
            self._save_record_transaction(
                table="download_jobs",
                id_column="job_id",
                record_id=job.job_id,
                project_id=job.project_id,
                status=job.status.value,
                record=job,
                expected_version=expected_version,
                model=DownloadJob,
                label="download job",
            ),
        )

    def get_download_job(self, job_id: str) -> DownloadJob | None:
        """Return one strict download job by id."""

        return self._get_record(
            "download_jobs",
            "job_id",
            job_id,
            DownloadJob,
            "download job",
        )

    def save_artifact_promotion_proof(
        self,
        proof: ArtifactPromotionProof,
    ) -> ArtifactPromotionProof:
        """Persist immutable validated-byte proof before filesystem promotion.

        The proof is accepted only while its exact download job is active and
        all job, URL, access-evidence, path, and project bindings match.
        """

        if not isinstance(proof, ArtifactPromotionProof):
            raise TypeError("proof must be ArtifactPromotionProof")
        if proof.state is not ArtifactPromotionState.PREPARED or proof.version != 1:
            raise ValueError("new promotion proof must be prepared at version 1")
        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            job_row = connection.execute(
                "SELECT raw_json FROM download_jobs WHERE job_id = ?",
                (proof.job_id,),
            ).fetchone()
            if job_row is None:
                raise AcquisitionStoreConflictError("promotion proof download job does not exist")
            job = self._load_model(job_row["raw_json"], DownloadJob, "download job")
            if job.status not in {DownloadJobStatus.RUNNING, DownloadJobStatus.VALIDATING}:
                raise AcquisitionStoreConflictError("promotion proof requires an active download job")
            if (
                proof.project_id != job.project_id
                or proof.candidate_id != job.candidate_id
                or proof.source_platform != job.source_platform
                or proof.source_url != job.source_url
                or proof.access_evidence.evidence_id != job.access_evidence_id
                or proof.relative_path != job.artifact_path
            ):
                raise AcquisitionStoreConflictError("promotion proof does not match its download job")

            digest = semantic_digest(proof)
            existing = connection.execute(
                "SELECT semantic_hash, raw_json FROM artifact_promotion_proofs WHERE proof_id = ?",
                (proof.proof_id,),
            ).fetchone()
            if existing is not None:
                if existing["semantic_hash"] != digest:
                    raise AcquisitionStoreConflictError(
                        "promotion proof id was reused for different facts"
                    )
                connection.commit()
                return self._load_model(
                    existing["raw_json"],
                    ArtifactPromotionProof,
                    "artifact promotion proof",
                )
            connection.execute(
                "INSERT INTO artifact_promotion_proofs("
                "proof_id, artifact_id, job_id, attempt_id, project_id, state, version, "
                "semantic_hash, raw_json, prepared_at, promoted_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    proof.proof_id,
                    proof.artifact_id,
                    proof.job_id,
                    proof.attempt_id,
                    proof.project_id,
                    proof.state.value,
                    proof.version,
                    digest,
                    proof.model_dump_json(),
                    _iso(proof.prepared_at),
                    None,
                ),
            )
            connection.commit()
            return self._load_model(
                proof.model_dump_json(),
                ArtifactPromotionProof,
                "artifact promotion proof",
            )
        except AcquisitionStoreError:
            connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise AcquisitionStoreConflictError(
                "promotion proof conflicts with existing audit state"
            ) from exc
        except sqlite3.Error as exc:
            connection.rollback()
            raise AcquisitionStoreError("promotion proof transaction failed") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_artifact_promotion_proof(
        self,
        artifact_id: str,
    ) -> ArtifactPromotionProof | None:
        """Return immutable promotion proof for one artifact id."""

        normalized = _normalize_identifier(artifact_id, "artifact_id")
        with closing(self._open_or_raise()) as connection:
            row = connection.execute(
                "SELECT raw_json FROM artifact_promotion_proofs WHERE artifact_id = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        return self._load_model(
            row["raw_json"],
            ArtifactPromotionProof,
            "artifact promotion proof",
        )

    def get_job_artifact_promotion_proof(
        self,
        job_id: str,
    ) -> ArtifactPromotionProof | None:
        """Return immutable promotion proof for one download job."""

        normalized = _normalize_identifier(job_id, "job_id")
        with closing(self._open_or_raise()) as connection:
            row = connection.execute(
                "SELECT raw_json FROM artifact_promotion_proofs WHERE job_id = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        return self._load_model(
            row["raw_json"],
            ArtifactPromotionProof,
            "artifact promotion proof",
        )

    def finalize_cancelled_download_cleanup(
        self,
        job_id: str,
        *,
        expected_version: int,
    ) -> DownloadJob:
        """Atomically invalidate prepared proof and close cancellation cleanup.

        Args:
            job_id: Stable cancelled download-job identifier.
            expected_version: Version observed after filesystem cleanup.

        Returns:
            Persisted cancelled job with cleanup errors cleared and byte count
            reset. The version advances when durable cleanup state changed.

        Raises:
            KeyError: If the download job does not exist.
            AcquisitionStoreConflictError: If the job changed, is not
                cancelled, or owns a non-prepared promotion proof.
            AcquisitionStoreError: If SQLite cannot commit the transaction.
        """

        if expected_version < 1:
            raise ValueError("expected_version must be positive")
        normalized_job_id = _normalize_identifier(job_id, "job_id")
        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT raw_json FROM download_jobs WHERE job_id = ?",
                (normalized_job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"download job not found: {normalized_job_id}")
            current = self._load_model(row["raw_json"], DownloadJob, "download job")
            if (
                current.version != expected_version
                or current.status is not DownloadJobStatus.CANCELLED
            ):
                raise AcquisitionStoreConflictError(
                    "cancelled download changed before cleanup finalization"
                )

            proof_row = connection.execute(
                "SELECT raw_json FROM artifact_promotion_proofs WHERE job_id = ?",
                (current.job_id,),
            ).fetchone()
            proof_removed = False
            if proof_row is not None:
                proof = self._load_model(
                    proof_row["raw_json"],
                    ArtifactPromotionProof,
                    "artifact promotion proof",
                )
                if (
                    proof.job_id != current.job_id
                    or proof.state is not ArtifactPromotionState.PREPARED
                ):
                    raise AcquisitionStoreConflictError(
                        "cancelled download owns a non-prepared promotion proof"
                    )
                cursor = connection.execute(
                    "DELETE FROM artifact_promotion_proofs WHERE proof_id = ? AND version = ?",
                    (proof.proof_id, proof.version),
                )
                if cursor.rowcount != 1:
                    raise AcquisitionStoreConflictError(
                        "promotion proof changed before cancellation cleanup"
                    )
                proof_removed = True

            cleanup_changed = (
                proof_removed
                or current.bytes_downloaded != 0
                or current.error_code is not None
                or current.error_message is not None
            )
            cleaned = current
            if cleanup_changed:
                cleaned = DownloadJob.model_validate(
                    current.model_copy(
                        update={
                            "bytes_downloaded": 0,
                            "error_code": None,
                            "error_message": None,
                            "version": current.version + 1,
                            "updated_at": utc_now(),
                        }
                    ).model_dump(mode="python")
                )
                self._update_existing_record(
                    connection,
                    table="download_jobs",
                    id_column="job_id",
                    record_id=current.job_id,
                    project_id=current.project_id,
                    status=cleaned.status.value,
                    record=cleaned,
                    expected_version=current.version,
                )
            connection.commit()
            return self._load_model(
                cleaned.model_dump_json(),
                DownloadJob,
                "download job",
            )
        except AcquisitionStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise AcquisitionStoreError(
                "download cancellation cleanup transaction failed"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def record_cancelled_download_cleanup_failure(
        self,
        job_id: str,
        *,
        expected_version: int,
        error_message: str,
    ) -> DownloadJob:
        """Persist a retryable cleanup failure on a cancelled download.

        Args:
            job_id: Stable cancelled download-job identifier.
            expected_version: Version observed by the cleanup caller.
            error_message: Bounded user-safe reason cleanup is incomplete.

        Returns:
            Persisted cancelled job carrying ``cancel_cleanup_failed``.

        Raises:
            KeyError: If the download job does not exist.
            AcquisitionStoreConflictError: If the job changed or is not
                cancelled.
            ValueError: If the replacement violates the download-job model.
            AcquisitionStoreError: If SQLite cannot commit the replacement.
        """

        if expected_version < 1:
            raise ValueError("expected_version must be positive")
        current = self.get_download_job(job_id)
        if current is None:
            raise KeyError(f"download job not found: {job_id}")
        if (
            current.version != expected_version
            or current.status is not DownloadJobStatus.CANCELLED
        ):
            raise AcquisitionStoreConflictError(
                "cancelled download changed before cleanup failure was recorded"
            )
        if (
            current.error_code == "cancel_cleanup_failed"
            and current.error_message == error_message
        ):
            return current
        failed = DownloadJob.model_validate(
            current.model_copy(
                update={
                    "error_code": "cancel_cleanup_failed",
                    "error_message": error_message,
                    "version": current.version + 1,
                    "updated_at": utc_now(),
                }
            ).model_dump(mode="python")
        )
        return self.save_download_job(failed, expected_version=current.version)

    def transition_download_job(
        self,
        job_id: str,
        *,
        expected_version: int,
        from_statuses: Sequence[DownloadJobStatus],
        to_status: DownloadJobStatus,
        attempts: int | None = None,
        bytes_downloaded: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        gate_id: str | None = None,
        artifact_id: str | None = None,
    ) -> DownloadJob:
        """CAS-transition one job while enforcing its current status.

        Args:
            job_id: Stable download-job id.
            expected_version: Version observed by the worker/controller.
            from_statuses: Allowed current statuses for this transition.
            to_status: Requested next status.
            attempts: Optional replacement attempt count.
            bytes_downloaded: Optional replacement streamed byte count.
            error_code: Optional bounded machine-readable error.
            error_message: Optional bounded user-safe detail.
            gate_id: Required for ``human_required``.
            artifact_id: Required for ``completed``.

        Returns:
            Persisted next-version job.
        """

        if expected_version < 1:
            raise ValueError("expected_version must be positive")
        allowed = frozenset(from_statuses)
        if not allowed:
            raise ValueError("from_statuses must be non-empty")
        current = self.get_download_job(job_id)
        if current is None:
            raise KeyError(f"download job not found: {job_id}")
        if current.version != expected_version or current.status not in allowed:
            raise AcquisitionStoreConflictError("download job state changed before transition")

        now = utc_now()
        updates: dict[str, object] = {
            "status": to_status,
            "version": current.version + 1,
            "updated_at": now,
            "error_code": error_code,
            "error_message": error_message,
            "gate_id": gate_id,
        }
        if to_status is DownloadJobStatus.RUNNING:
            next_attempts = current.attempts + 1 if attempts is None else attempts
            if next_attempts != current.attempts + 1:
                raise ValueError("running transition must increment attempts by one")
            updates["attempts"] = next_attempts
        elif attempts is not None:
            updates["attempts"] = attempts
        if bytes_downloaded is not None:
            updates["bytes_downloaded"] = bytes_downloaded
        if artifact_id is not None:
            updates["artifact_id"] = artifact_id
        if to_status is DownloadJobStatus.RUNNING and current.started_at is None:
            updates["started_at"] = now
        if to_status is DownloadJobStatus.COMPLETED:
            updates["completed_at"] = now
        next_job = DownloadJob.model_validate(current.model_copy(update=updates).model_dump(mode="python"))
        return self.save_download_job(next_job, expected_version=current.version)

    def settle_download_job(
        self,
        job_id: str,
        *,
        expected_version: int,
        from_statuses: Sequence[DownloadJobStatus],
        to_status: DownloadJobStatus,
        attempt: AcquisitionAttempt,
        bytes_downloaded: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        gate: HumanAccessGate | None = None,
    ) -> tuple[DownloadJob, AcquisitionAttempt, HumanAccessGate | None]:
        """Atomically settle one invocation, its job, and an optional access gate.

        Args:
            job_id: Stable download-job id.
            expected_version: Job version observed by the worker.
            from_statuses: Allowed active states for the settlement.
            to_status: Non-completion terminal state for this invocation.
            attempt: Immutable terminal audit record for the current ordinal.
            bytes_downloaded: Optional replacement streamed-byte count.
            error_code: Optional job error code; defaults to the attempt error class.
            error_message: Optional job detail; defaults to the attempt detail.
            gate: New open gate when settling as ``human_required``.

        Returns:
            Canonical persisted job, attempt, and optional gate.

        Raises:
            AcquisitionStoreConflictError: If any owner, ordinal, outcome, or
                compare-and-swap binding differs from the persisted job.
            ValueError: If the target is not a supported terminal settlement.
        """

        if expected_version < 1:
            raise ValueError("expected_version must be positive")
        if not isinstance(attempt, AcquisitionAttempt):
            raise TypeError("attempt must be AcquisitionAttempt")
        if gate is not None and not isinstance(gate, HumanAccessGate):
            raise TypeError("gate must be HumanAccessGate or None")
        allowed = frozenset(from_statuses)
        if not allowed:
            raise ValueError("from_statuses must be non-empty")
        if to_status not in _SETTLED_DOWNLOAD_OUTCOMES:
            raise ValueError("to_status must settle a non-completion download outcome")
        if (to_status is DownloadJobStatus.HUMAN_REQUIRED) != (gate is not None):
            raise ValueError("human_required settlement requires exactly one gate")

        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT raw_json FROM download_jobs WHERE job_id = ?",
                (_normalize_identifier(job_id, "job_id"),),
            ).fetchone()
            if row is None:
                raise KeyError(f"download job not found: {job_id}")
            current = self._load_model(row["raw_json"], DownloadJob, "download job")
            if current.version != expected_version or current.status not in allowed:
                raise AcquisitionStoreConflictError(
                    "download job state changed before attempt settlement"
                )
            self._validate_download_attempt(current, to_status=to_status, attempt=attempt)
            if error_code is not None and attempt.error_class not in {None, error_code}:
                raise AcquisitionStoreConflictError("job and attempt error codes disagree")
            if error_message is not None and attempt.error_message not in {None, error_message}:
                raise AcquisitionStoreConflictError("job and attempt error messages disagree")

            stored_gate: HumanAccessGate | None = None
            if gate is not None:
                self._validate_download_gate(current, attempt=attempt, gate=gate)
                stored_gate = cast(
                    HumanAccessGate,
                    self._save_versioned_record(
                        connection,
                        table="human_gates",
                        id_column="gate_id",
                        record_id=gate.gate_id,
                        project_id=gate.project_id,
                        status=gate.status.value,
                        record=gate,
                        expected_version=None,
                    ),
                )

            now = utc_now()
            updates: dict[str, object] = {
                "status": to_status,
                "version": current.version + 1,
                "updated_at": now,
                "error_code": error_code if error_code is not None else attempt.error_class,
                "error_message": (
                    error_message if error_message is not None else attempt.error_message
                ),
                "gate_id": stored_gate.gate_id if stored_gate is not None else None,
            }
            if bytes_downloaded is not None:
                updates["bytes_downloaded"] = bytes_downloaded
            settled = DownloadJob.model_validate(
                current.model_copy(update=updates).model_dump(mode="python")
            )
            self._update_existing_record(
                connection,
                table="download_jobs",
                id_column="job_id",
                record_id=current.job_id,
                project_id=current.project_id,
                status=settled.status.value,
                record=settled,
                expected_version=current.version,
            )
            stored_attempt = self._insert_acquisition_attempt(connection, attempt)
            connection.commit()
            return (
                self._load_model(settled.model_dump_json(), DownloadJob, "download job"),
                stored_attempt,
                (
                    None
                    if stored_gate is None
                    else self._load_model(
                        stored_gate.model_dump_json(),
                        HumanAccessGate,
                        "human gate",
                    )
                ),
            )
        except AcquisitionStoreError:
            connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise AcquisitionStoreConflictError(
                "download attempt settlement conflicts with existing state"
            ) from exc
        except sqlite3.Error as exc:
            connection.rollback()
            raise AcquisitionStoreError("download attempt settlement transaction failed") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def complete_download_job(
        self,
        artifact: ValidatedArtifact,
        promotion_proof: ArtifactPromotionProof,
        *,
        expected_job_version: int,
        attempt: AcquisitionAttempt | None = None,
    ) -> DownloadJob:
        """Verify proof and atomically persist artifact, job, and optional attempt."""

        if not isinstance(artifact, ValidatedArtifact):
            raise TypeError("artifact must be ValidatedArtifact")
        if not isinstance(promotion_proof, ArtifactPromotionProof):
            raise TypeError("promotion_proof must be ArtifactPromotionProof")
        if attempt is not None and not isinstance(attempt, AcquisitionAttempt):
            raise TypeError("attempt must be AcquisitionAttempt or None")
        if expected_job_version < 1:
            raise ValueError("expected_job_version must be positive")
        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT raw_json FROM download_jobs WHERE job_id = ?",
                (artifact.job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"download job not found: {artifact.job_id}")
            current = self._load_model(row["raw_json"], DownloadJob, "download job")
            if (
                current.version != expected_job_version
                or current.status is not DownloadJobStatus.VALIDATING
            ):
                raise AcquisitionStoreConflictError("download job changed before completion")
            if attempt is not None:
                self._validate_download_attempt(
                    current,
                    to_status=DownloadJobStatus.COMPLETED,
                    attempt=attempt,
                )
            if (
                artifact.project_id != current.project_id
                or artifact.candidate_id != current.candidate_id
                or artifact.relative_path != current.artifact_path
            ):
                raise AcquisitionStoreConflictError("artifact does not match its download job")
            proof_row = connection.execute(
                "SELECT semantic_hash, raw_json FROM artifact_promotion_proofs "
                "WHERE artifact_id = ? AND job_id = ?",
                (artifact.artifact_id, artifact.job_id),
            ).fetchone()
            if proof_row is None:
                raise AcquisitionStoreConflictError("artifact promotion proof is missing")
            stored_proof = self._load_model(
                proof_row["raw_json"],
                ArtifactPromotionProof,
                "artifact promotion proof",
            )
            if proof_row["semantic_hash"] != semantic_digest(promotion_proof):
                raise AcquisitionStoreConflictError("artifact promotion proof changed before completion")
            if stored_proof != promotion_proof:
                raise AcquisitionStoreConflictError("artifact promotion proof does not match stored facts")
            if stored_proof.state is not ArtifactPromotionState.PREPARED:
                raise AcquisitionStoreConflictError("artifact promotion proof is not prepared")
            if (
                stored_proof.project_id != artifact.project_id
                or stored_proof.candidate_id != artifact.candidate_id
                or stored_proof.relative_path != artifact.relative_path
                or stored_proof.size_bytes != artifact.size_bytes
                or stored_proof.sha256 != artifact.sha256
                or stored_proof.page_count != artifact.page_count
                or stored_proof.source_platform != current.source_platform
                or stored_proof.source_url != current.source_url
                or stored_proof.access_evidence.evidence_id != current.access_evidence_id
            ):
                raise AcquisitionStoreConflictError("artifact does not match its promotion proof")

            now = utc_now()
            promoted_proof = ArtifactPromotionProof.model_validate(
                stored_proof.model_copy(
                    update={
                        "state": ArtifactPromotionState.PROMOTED,
                        "version": stored_proof.version + 1,
                        "promoted_at": now,
                    }
                ).model_dump(mode="python")
            )
            completed = DownloadJob.model_validate(
                current.model_copy(
                    update={
                        "status": DownloadJobStatus.COMPLETED,
                        "version": current.version + 1,
                        "updated_at": now,
                        "completed_at": now,
                        "bytes_downloaded": artifact.size_bytes,
                        "error_code": None,
                        "error_message": None,
                        "gate_id": None,
                        "artifact_id": artifact.artifact_id,
                    }
                ).model_dump(mode="python")
            )
            self._save_versioned_record(
                connection,
                table="validated_artifacts",
                id_column="artifact_id",
                record_id=artifact.artifact_id,
                project_id=artifact.project_id,
                status="valid",
                record=artifact,
                expected_version=None,
            )
            self._update_existing_record(
                connection,
                table="download_jobs",
                id_column="job_id",
                record_id=current.job_id,
                project_id=current.project_id,
                status=completed.status.value,
                record=completed,
                expected_version=current.version,
            )
            proof_cursor = connection.execute(
                "UPDATE artifact_promotion_proofs SET state = ?, version = ?, semantic_hash = ?, "
                "raw_json = ?, promoted_at = ? WHERE proof_id = ? AND version = ?",
                (
                    promoted_proof.state.value,
                    promoted_proof.version,
                    semantic_digest(promoted_proof),
                    promoted_proof.model_dump_json(),
                    _iso(now),
                    promoted_proof.proof_id,
                    stored_proof.version,
                ),
            )
            if proof_cursor.rowcount != 1:
                raise AcquisitionStoreConflictError("promotion proof changed before completion")
            if attempt is not None:
                self._insert_acquisition_attempt(connection, attempt)
            connection.commit()
            return self._load_model(completed.model_dump_json(), DownloadJob, "download job")
        except AcquisitionStoreError:
            connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise AcquisitionStoreConflictError("artifact conflicts with existing state") from exc
        except sqlite3.Error as exc:
            connection.rollback()
            raise AcquisitionStoreError("download completion transaction failed") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_download_jobs(
        self,
        *,
        project_id: str | None = None,
        statuses: Sequence[DownloadJobStatus] = (),
        limit: int = 100,
    ) -> tuple[DownloadJob, ...]:
        """List bounded jobs by project and allowlisted status values."""

        bounded_limit = _validate_limit(limit)
        where: list[str] = []
        parameters: list[object] = []
        if project_id is not None:
            where.append("project_id = ?")
            parameters.append(_normalize_identifier(project_id, "project_id"))
        normalized_statuses = tuple(dict.fromkeys(status.value for status in statuses))
        if normalized_statuses:
            placeholders = ",".join("?" for _ in normalized_statuses)
            where.append(f"status IN ({placeholders})")
            parameters.extend(normalized_statuses)
        query = "SELECT raw_json FROM download_jobs"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY created_at ASC, job_id ASC LIMIT ?"
        parameters.append(bounded_limit)
        with closing(self._open_or_raise()) as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return tuple(self._load_model(row["raw_json"], DownloadJob, "download job") for row in rows)

    def recover_interrupted_jobs(self) -> tuple[DownloadJob, ...]:
        """Reset interrupted workers to queued without launching network work.

        Only ``running`` and ``validating`` are recovered. Paused, cancelled,
        gated, failed, and completed jobs retain their explicit meaning.
        Existing ``.part`` metadata remains available for a later explicit
        resume attempt, which may restart the transfer when byte ranges are not
        supported by the source.
        """

        connection = self._open_or_raise()
        recovered: list[DownloadJob] = []
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT raw_json FROM download_jobs WHERE status IN (?, ?) "
                "ORDER BY created_at ASC, job_id ASC",
                (DownloadJobStatus.RUNNING.value, DownloadJobStatus.VALIDATING.value),
            ).fetchall()
            for row in rows:
                current = self._load_model(row["raw_json"], DownloadJob, "download job")
                if current.attempts < 1:
                    raise AcquisitionStoreCorruptionError(
                        "active download job has no invocation ordinal"
                    )
                now = utc_now()
                attempt_started_at = current.started_at or current.updated_at
                elapsed_ms = min(
                    86_400_000,
                    max(0, int((now - attempt_started_at).total_seconds() * 1000)),
                )
                interrupted_attempt = AcquisitionAttempt(
                    attempt_id=_download_attempt_id(current.job_id, current.attempts),
                    project_id=current.project_id,
                    job_id=current.job_id,
                    source_id=current.source_platform,
                    stage=AcquisitionAttemptStage.DOWNLOAD,
                    outcome=AcquisitionAttemptOutcome.FAILED,
                    ordinal=current.attempts,
                    error_class="interrupted_restart",
                    error_message=(
                        "Previous worker stopped before completion; explicit resume is available."
                    ),
                    elapsed_ms=elapsed_ms,
                    retryable=True,
                    started_at=attempt_started_at,
                    finished_at=now,
                )
                next_job = DownloadJob.model_validate(
                    current.model_copy(
                        update={
                            "status": DownloadJobStatus.QUEUED,
                            "version": current.version + 1,
                            "updated_at": now,
                            "error_code": "interrupted_restart",
                            "error_message": "Previous worker stopped before completion; explicit resume is available.",
                            "gate_id": None,
                        }
                    ).model_dump(mode="python")
                )
                self._update_existing_record(
                    connection,
                    table="download_jobs",
                    id_column="job_id",
                    record_id=current.job_id,
                    project_id=current.project_id,
                    status=next_job.status.value,
                    record=next_job,
                    expected_version=current.version,
                )
                self._insert_acquisition_attempt(connection, interrupted_attempt)
                recovered.append(next_job)
            connection.commit()
            return tuple(recovered)
        except AcquisitionStoreError:
            connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise AcquisitionStoreConflictError(
                "interrupted download attempt conflicts with existing state"
            ) from exc
        except sqlite3.Error as exc:
            connection.rollback()
            raise AcquisitionStoreError("download recovery transaction failed") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save_gate(
        self,
        gate: HumanAccessGate,
        *,
        expected_version: int | None = None,
    ) -> HumanAccessGate:
        """Create or CAS-replace one human access gate."""

        if not isinstance(gate, HumanAccessGate):
            raise TypeError("gate must be HumanAccessGate")
        return cast(
            HumanAccessGate,
            self._save_record_transaction(
                table="human_gates",
                id_column="gate_id",
                record_id=gate.gate_id,
                project_id=gate.project_id,
                status=gate.status.value,
                record=gate,
                expected_version=expected_version,
                model=HumanAccessGate,
                label="human gate",
            ),
        )

    def resolve_gate(self, gate_id: str, *, expected_version: int) -> HumanAccessGate:
        """Mark one open gate resolved after an explicit user action.

        Args:
            gate_id: Stable gate identifier returned to the caller.
            expected_version: Version observed by the resolving caller.

        Returns:
            Persisted next-version resolved gate.

        Raises:
            KeyError: If the gate does not exist.
            AcquisitionStoreConflictError: If the gate is already resolved or
                changed since the caller read it.
        """

        current = self.get_gate(gate_id)
        if current is None:
            raise KeyError(f"human gate not found: {gate_id}")
        if current.version != expected_version or current.status is not GateStatus.OPEN:
            raise AcquisitionStoreConflictError("human gate state changed before resolution")
        now = utc_now()
        resolved = HumanAccessGate.model_validate(
            current.model_copy(
                update={
                    "status": GateStatus.RESOLVED,
                    "version": current.version + 1,
                    "updated_at": now,
                    "resolved_at": now,
                }
            ).model_dump(mode="python")
        )
        return self.save_gate(resolved, expected_version=current.version)

    def resolve_gate_and_requeue_download(
        self,
        gate_id: str,
        *,
        expected_gate_version: int,
        expected_job_version: int,
    ) -> tuple[HumanAccessGate, DownloadJob]:
        """Resolve a download gate and requeue its owned job atomically."""

        if expected_gate_version < 1 or expected_job_version < 1:
            raise ValueError("expected versions must be positive")
        normalized_gate_id = _normalize_identifier(gate_id, "gate_id")
        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            gate_row = connection.execute(
                "SELECT raw_json FROM human_gates WHERE gate_id = ?",
                (normalized_gate_id,),
            ).fetchone()
            if gate_row is None:
                raise KeyError(f"human gate not found: {normalized_gate_id}")
            gate = self._load_model(gate_row["raw_json"], HumanAccessGate, "human gate")
            if gate.job_id is None:
                raise AcquisitionStoreConflictError("human gate does not own a download job")
            job_row = connection.execute(
                "SELECT raw_json FROM download_jobs WHERE job_id = ?",
                (gate.job_id,),
            ).fetchone()
            if job_row is None:
                raise AcquisitionStoreConflictError("human gate download job is missing")
            job = self._load_model(job_row["raw_json"], DownloadJob, "download job")
            if (
                gate.version != expected_gate_version
                or gate.status is not GateStatus.OPEN
                or job.version != expected_job_version
                or job.status is not DownloadJobStatus.HUMAN_REQUIRED
                or job.gate_id != gate.gate_id
                or job.project_id != gate.project_id
            ):
                raise AcquisitionStoreConflictError("gate or download job changed before resolution")

            now = utc_now()
            resolved = HumanAccessGate.model_validate(
                gate.model_copy(
                    update={
                        "status": GateStatus.RESOLVED,
                        "version": gate.version + 1,
                        "updated_at": now,
                        "resolved_at": now,
                    }
                ).model_dump(mode="python")
            )
            queued = DownloadJob.model_validate(
                job.model_copy(
                    update={
                        "status": DownloadJobStatus.QUEUED,
                        "version": job.version + 1,
                        "updated_at": now,
                        "error_code": None,
                        "error_message": None,
                        "gate_id": None,
                    }
                ).model_dump(mode="python")
            )
            self._update_existing_record(
                connection,
                table="human_gates",
                id_column="gate_id",
                record_id=gate.gate_id,
                project_id=gate.project_id,
                status=resolved.status.value,
                record=resolved,
                expected_version=gate.version,
            )
            self._update_existing_record(
                connection,
                table="download_jobs",
                id_column="job_id",
                record_id=job.job_id,
                project_id=job.project_id,
                status=queued.status.value,
                record=queued,
                expected_version=job.version,
            )
            connection.commit()
            return (
                self._load_model(resolved.model_dump_json(), HumanAccessGate, "human gate"),
                self._load_model(queued.model_dump_json(), DownloadJob, "download job"),
            )
        except AcquisitionStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise AcquisitionStoreError("gate resolution transaction failed") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_gate(self, gate_id: str) -> HumanAccessGate | None:
        """Return one strict human gate."""

        return self._get_record(
            "human_gates",
            "gate_id",
            gate_id,
            HumanAccessGate,
            "human gate",
        )

    def list_gates(
        self,
        *,
        project_id: str | None = None,
        statuses: Sequence[GateStatus] = (),
        limit: int = 100,
    ) -> tuple[HumanAccessGate, ...]:
        """List bounded human gates by project and status."""

        bounded_limit = _validate_limit(limit)
        where: list[str] = []
        parameters: list[object] = []
        if project_id is not None:
            where.append("project_id = ?")
            parameters.append(_normalize_identifier(project_id, "project_id"))
        normalized_statuses = tuple(dict.fromkeys(status.value for status in statuses))
        if normalized_statuses:
            placeholders = ",".join("?" for _ in normalized_statuses)
            where.append(f"status IN ({placeholders})")
            parameters.extend(normalized_statuses)
        query = "SELECT raw_json FROM human_gates"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY created_at ASC, gate_id ASC LIMIT ?"
        parameters.append(bounded_limit)
        with closing(self._open_or_raise()) as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return tuple(self._load_model(row["raw_json"], HumanAccessGate, "human gate") for row in rows)

    def save_artifact(self, artifact: ValidatedArtifact) -> ValidatedArtifact:
        """Persist one idempotent validated artifact record."""

        if not isinstance(artifact, ValidatedArtifact):
            raise TypeError("artifact must be ValidatedArtifact")
        return cast(
            ValidatedArtifact,
            self._save_record_transaction(
                table="validated_artifacts",
                id_column="artifact_id",
                record_id=artifact.artifact_id,
                project_id=artifact.project_id,
                status="valid",
                record=artifact,
                expected_version=None,
                model=ValidatedArtifact,
                label="validated artifact",
            ),
        )

    def get_artifact(self, artifact_id: str) -> ValidatedArtifact | None:
        """Return one strict validated artifact."""

        return self._get_record(
            "validated_artifacts",
            "artifact_id",
            artifact_id,
            ValidatedArtifact,
            "validated artifact",
        )

    def save_import_receipt(
        self,
        receipt: ImportReceipt,
        *,
        expected_version: int | None = None,
    ) -> ImportReceipt:
        """Create or CAS-replace one existing-project import receipt."""

        if not isinstance(receipt, ImportReceipt):
            raise TypeError("receipt must be ImportReceipt")
        return cast(
            ImportReceipt,
            self._save_record_transaction(
                table="import_receipts",
                id_column="receipt_id",
                record_id=receipt.receipt_id,
                project_id=receipt.project_id,
                status=receipt.status.value,
                record=receipt,
                expected_version=expected_version,
                model=ImportReceipt,
                label="import receipt",
            ),
        )

    def get_import_receipt(self, receipt_id: str) -> ImportReceipt | None:
        """Return one strict import receipt."""

        return self._get_record(
            "import_receipts",
            "receipt_id",
            receipt_id,
            ImportReceipt,
            "import receipt",
        )

    def list_import_receipts(
        self,
        *,
        project_id: str | None = None,
        statuses: Sequence[ImportStatus] = (),
        publication_states: Sequence[ImportPublicationState] = (),
        limit: int = 100,
    ) -> tuple[ImportReceipt, ...]:
        """List bounded import receipts by lifecycle and publication state.

        Args:
            project_id: Optional exact project owner.
            statuses: Optional import lifecycle filter.
            publication_states: Optional publication-integrity filter.
            limit: Maximum number of receipts, capped by the store limit.

        Returns:
            Stable creation-order receipts matching every supplied filter.
        """

        bounded_limit = _validate_limit(limit)
        where: list[str] = []
        parameters: list[object] = []
        if project_id is not None:
            where.append("project_id = ?")
            parameters.append(_normalize_identifier(project_id, "project_id"))
        normalized_statuses = tuple(dict.fromkeys(status.value for status in statuses))
        if normalized_statuses:
            placeholders = ",".join("?" for _ in normalized_statuses)
            where.append(f"status IN ({placeholders})")
            parameters.extend(normalized_statuses)
        normalized_publication_states = tuple(
            dict.fromkeys(state.value for state in publication_states)
        )
        if normalized_publication_states:
            placeholders = ",".join("?" for _ in normalized_publication_states)
            where.append(
                f"json_extract(raw_json, '$.publication_state') IN ({placeholders})"
            )
            parameters.extend(normalized_publication_states)
        query = "SELECT raw_json FROM import_receipts"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY created_at ASC, receipt_id ASC LIMIT ?"
        parameters.append(bounded_limit)
        with closing(self._open_or_raise()) as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return tuple(self._load_model(row["raw_json"], ImportReceipt, "import receipt") for row in rows)

    @staticmethod
    def _validate_download_attempt(
        job: DownloadJob,
        *,
        to_status: DownloadJobStatus,
        attempt: AcquisitionAttempt,
    ) -> None:
        expected_outcome = _TERMINAL_DOWNLOAD_OUTCOMES.get(to_status)
        if expected_outcome is None:
            raise ValueError("to_status does not have a terminal attempt outcome")
        expected_attempt_id = _download_attempt_id(job.job_id, job.attempts)
        if (
            attempt.attempt_id != expected_attempt_id
            or attempt.job_id != job.job_id
            or attempt.run_id is not None
            or attempt.project_id != job.project_id
            or attempt.source_id != job.source_platform
            or attempt.stage is not AcquisitionAttemptStage.DOWNLOAD
            or attempt.ordinal != job.attempts
            or attempt.outcome is not expected_outcome
        ):
            raise AcquisitionStoreConflictError(
                "download attempt does not match its job, ordinal, or terminal outcome"
            )

    @staticmethod
    def _validate_download_gate(
        job: DownloadJob,
        *,
        attempt: AcquisitionAttempt,
        gate: HumanAccessGate,
    ) -> None:
        if (
            gate.job_id != job.job_id
            or gate.project_id != job.project_id
            or gate.platform != job.source_platform
            or gate.status is not GateStatus.OPEN
            or gate.resume_status is not DownloadJobStatus.QUEUED
            or gate.version != 1
            or attempt.gate_id != gate.gate_id
            or attempt.next_action != gate.next_action
        ):
            raise AcquisitionStoreConflictError(
                "human access gate does not match its download attempt"
            )

    def _insert_acquisition_attempt(
        self,
        connection: sqlite3.Connection,
        attempt: AcquisitionAttempt,
    ) -> AcquisitionAttempt:
        """Insert an immutable attempt inside the caller-owned transaction."""

        owner_table = "search_runs" if attempt.run_id is not None else "download_jobs"
        owner_column = "run_id" if attempt.run_id is not None else "job_id"
        owner_id = attempt.run_id or attempt.job_id
        owner = connection.execute(
            f"SELECT project_id FROM {owner_table} WHERE {owner_column} = ?",
            (owner_id,),
        ).fetchone()
        if owner is None:
            raise AcquisitionStoreConflictError("acquisition attempt owner does not exist")
        if owner["project_id"] != attempt.project_id:
            raise AcquisitionStoreConflictError(
                "acquisition attempt project does not match its owner"
            )

        digest = semantic_digest(attempt)
        existing = connection.execute(
            "SELECT semantic_hash, raw_json FROM acquisition_attempts WHERE attempt_id = ?",
            (attempt.attempt_id,),
        ).fetchone()
        if existing is not None:
            if existing["semantic_hash"] != digest:
                raise AcquisitionStoreConflictError(
                    "acquisition attempt id was reused for different facts"
                )
            return self._load_model(
                existing["raw_json"],
                AcquisitionAttempt,
                "acquisition attempt",
            )
        connection.execute(
            "INSERT INTO acquisition_attempts("
            "attempt_id, project_id, run_id, job_id, source_id, stage, outcome, ordinal, "
            "semantic_hash, raw_json, started_at, finished_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                attempt.attempt_id,
                attempt.project_id,
                attempt.run_id,
                attempt.job_id,
                attempt.source_id,
                attempt.stage.value,
                attempt.outcome.value,
                attempt.ordinal,
                digest,
                attempt.model_dump_json(),
                _iso(attempt.started_at),
                _iso(attempt.finished_at),
            ),
        )
        return self._load_model(
            attempt.model_dump_json(),
            AcquisitionAttempt,
            "acquisition attempt",
        )

    def _initialize_schema(self) -> None:
        connection = self._open_or_raise(initialize=True)
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS acquisition_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS search_runs (
                    run_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    semantic_hash TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_search_runs_project_status
                    ON search_runs(project_id, status, created_at);
                CREATE TABLE IF NOT EXISTS candidates (
                    candidate_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    semantic_hash TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES search_runs(run_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_candidates_run
                    ON candidates(run_id, created_at);
                CREATE TABLE IF NOT EXISTS identity_merge_receipts (
                    merge_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    canonical_candidate_id TEXT NOT NULL,
                    compared_candidate_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    method TEXT NOT NULL,
                    semantic_hash TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES search_runs(run_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_identity_receipts_run
                    ON identity_merge_receipts(run_id, created_at, merge_id);
                CREATE TABLE IF NOT EXISTS candidate_version_relations (
                    relation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    source_candidate_id TEXT NOT NULL,
                    target_candidate_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    evidence_kind TEXT NOT NULL,
                    semantic_hash TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES search_runs(run_id) ON DELETE CASCADE,
                    FOREIGN KEY(source_candidate_id) REFERENCES candidates(candidate_id),
                    FOREIGN KEY(target_candidate_id) REFERENCES candidates(candidate_id)
                );
                CREATE INDEX IF NOT EXISTS idx_version_relations_run
                    ON candidate_version_relations(run_id, created_at, relation_id);
                CREATE TABLE IF NOT EXISTS download_jobs (
                    job_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    semantic_hash TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_download_jobs_project_status
                    ON download_jobs(project_id, status, created_at);
                CREATE TABLE IF NOT EXISTS acquisition_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    run_id TEXT,
                    job_id TEXT,
                    source_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    semantic_hash TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    CHECK ((run_id IS NULL) <> (job_id IS NULL)),
                    FOREIGN KEY(run_id) REFERENCES search_runs(run_id),
                    FOREIGN KEY(job_id) REFERENCES download_jobs(job_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_attempts_run_ordinal
                    ON acquisition_attempts(run_id, source_id, stage, ordinal)
                    WHERE run_id IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_attempts_job_ordinal
                    ON acquisition_attempts(job_id, source_id, stage, ordinal)
                    WHERE job_id IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_attempts_run_order
                    ON acquisition_attempts(run_id, ordinal, started_at, attempt_id);
                CREATE INDEX IF NOT EXISTS idx_attempts_job_order
                    ON acquisition_attempts(job_id, ordinal, started_at, attempt_id);
                CREATE TABLE IF NOT EXISTS artifact_promotion_proofs (
                    proof_id TEXT PRIMARY KEY,
                    artifact_id TEXT NOT NULL UNIQUE,
                    job_id TEXT NOT NULL UNIQUE,
                    attempt_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    semantic_hash TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    prepared_at TEXT NOT NULL,
                    promoted_at TEXT,
                    FOREIGN KEY(job_id) REFERENCES download_jobs(job_id)
                );
                CREATE INDEX IF NOT EXISTS idx_promotion_proofs_project
                    ON artifact_promotion_proofs(project_id, prepared_at, proof_id);
                CREATE TABLE IF NOT EXISTS human_gates (
                    gate_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    semantic_hash TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS validated_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    semantic_hash TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_artifacts_job
                    ON validated_artifacts(json_extract(raw_json, '$.job_id'));
                CREATE TABLE IF NOT EXISTS import_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    semantic_hash TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_receipts_artifact
                    ON import_receipts(json_extract(raw_json, '$.artifact_id'));
                """
            )
            existing = connection.execute(
                "SELECT value FROM acquisition_meta WHERE key = 'schema_version'"
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO acquisition_meta(key, value) VALUES ('schema_version', ?)",
                    (str(ACQUISITION_STORE_SCHEMA_VERSION),),
                )
            elif int(existing["value"]) in {1, 2}:
                connection.execute(
                    "UPDATE acquisition_meta SET value = ? WHERE key = 'schema_version'",
                    (str(ACQUISITION_STORE_SCHEMA_VERSION),),
                )
            elif int(existing["value"]) != ACQUISITION_STORE_SCHEMA_VERSION:
                raise AcquisitionStoreError("unsupported acquisition store schema version")
            connection.commit()
        except AcquisitionStoreError:
            connection.rollback()
            raise
        except (sqlite3.Error, ValueError) as exc:
            connection.rollback()
            raise AcquisitionStoreError("unable to initialize acquisition store") from exc
        finally:
            connection.close()

    @staticmethod
    def _validate_search_run_ledgers(
        run: SearchRun,
        receipts: tuple[IdentityMergeReceipt, ...],
        relations: tuple[CandidateVersionRelation, ...],
    ) -> None:
        if any(not isinstance(receipt, IdentityMergeReceipt) for receipt in receipts):
            raise TypeError("identity_receipts must contain IdentityMergeReceipt records")
        if any(not isinstance(relation, CandidateVersionRelation) for relation in relations):
            raise TypeError("version_relations must contain CandidateVersionRelation records")
        if len({receipt.merge_id for receipt in receipts}) != len(receipts):
            raise ValueError("identity receipt ids must be unique within one run")
        if len({relation.relation_id for relation in relations}) != len(relations):
            raise ValueError("version relation ids must be unique within one run")
        candidates_by_id = {candidate.candidate_id: candidate for candidate in run.candidates}
        for receipt in receipts:
            if receipt.run_id != run.run_id or receipt.project_id != run.query.project_id:
                raise ValueError("identity receipt must belong to the saved search run")
            canonical = candidates_by_id.get(receipt.canonical_candidate_id)
            if canonical is None:
                raise AcquisitionStoreConflictError(
                    "identity receipt canonical candidate must belong to the saved search run"
                )
            if receipt.merged:
                if receipt.compared_candidate_id not in canonical.merged_from_candidate_ids:
                    raise AcquisitionStoreConflictError(
                        "merged identity receipt must match retained candidate provenance"
                    )
            elif receipt.compared_candidate_id not in candidates_by_id:
                raise AcquisitionStoreConflictError(
                    "distinct identity receipt candidates must belong to the saved search run"
                )
        for relation in relations:
            if relation.run_id != run.run_id or relation.project_id != run.query.project_id:
                raise ValueError("version relation must belong to the saved search run")
            source = candidates_by_id.get(relation.source_candidate_id)
            target = candidates_by_id.get(relation.target_candidate_id)
            if source is None or target is None:
                raise AcquisitionStoreConflictError(
                    "version relation endpoints must belong to the saved search run"
                )
            expected = build_explicit_version_relation(
                source,
                target,
                created_at=relation.created_at,
            )
            if expected != relation:
                raise AcquisitionStoreConflictError(
                    "version relation is not supported by retained candidate provenance"
                )

    def _replace_search_run_children(
        self,
        connection: sqlite3.Connection,
        run: SearchRun,
        receipts: tuple[IdentityMergeReceipt, ...],
        relations: tuple[CandidateVersionRelation, ...],
    ) -> None:
        connection.execute("DELETE FROM candidate_version_relations WHERE run_id = ?", (run.run_id,))
        connection.execute("DELETE FROM identity_merge_receipts WHERE run_id = ?", (run.run_id,))
        self._replace_run_candidates(connection, run)
        for receipt in receipts:
            connection.execute(
                "INSERT INTO identity_merge_receipts("
                "merge_id, run_id, project_id, canonical_candidate_id, compared_candidate_id, "
                "outcome, method, semantic_hash, raw_json, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    receipt.merge_id,
                    receipt.run_id,
                    receipt.project_id,
                    receipt.canonical_candidate_id,
                    receipt.compared_candidate_id,
                    receipt.outcome.value,
                    receipt.method.value,
                    semantic_digest(receipt),
                    receipt.model_dump_json(),
                    _iso(receipt.created_at),
                ),
            )
        for relation in relations:
            connection.execute(
                "INSERT INTO candidate_version_relations("
                "relation_id, run_id, project_id, source_candidate_id, target_candidate_id, "
                "relation, evidence_kind, semantic_hash, raw_json, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    relation.relation_id,
                    relation.run_id,
                    relation.project_id,
                    relation.source_candidate_id,
                    relation.target_candidate_id,
                    relation.relation.value,
                    relation.evidence_kind.value,
                    semantic_digest(relation),
                    relation.model_dump_json(),
                    _iso(relation.created_at),
                ),
            )

    @staticmethod
    def _assert_search_run_children_match(
        connection: sqlite3.Connection,
        run: SearchRun,
        receipts: tuple[IdentityMergeReceipt, ...],
        relations: tuple[CandidateVersionRelation, ...],
    ) -> None:
        expected_candidates = {
            candidate.candidate_id: semantic_digest(candidate) for candidate in run.candidates
        }
        stored_candidates = {
            row["candidate_id"]: row["semantic_hash"]
            for row in connection.execute(
                "SELECT candidate_id, semantic_hash FROM candidates WHERE run_id = ?",
                (run.run_id,),
            ).fetchall()
        }
        expected_receipts = {
            receipt.merge_id: semantic_digest(receipt) for receipt in receipts
        }
        stored_receipts = {
            row["merge_id"]: row["semantic_hash"]
            for row in connection.execute(
                "SELECT merge_id, semantic_hash FROM identity_merge_receipts WHERE run_id = ?",
                (run.run_id,),
            ).fetchall()
        }
        expected_relations = {
            relation.relation_id: semantic_digest(relation) for relation in relations
        }
        stored_relations = {
            row["relation_id"]: row["semantic_hash"]
            for row in connection.execute(
                "SELECT relation_id, semantic_hash FROM candidate_version_relations WHERE run_id = ?",
                (run.run_id,),
            ).fetchall()
        }
        if (
            expected_candidates != stored_candidates
            or expected_receipts != stored_receipts
            or expected_relations != stored_relations
        ):
            raise AcquisitionStoreConflictError(
                "stable search run id was reused with different child records"
            )

    def _replace_run_candidates(self, connection: sqlite3.Connection, run: SearchRun) -> None:
        connection.execute("DELETE FROM candidates WHERE run_id = ?", (run.run_id,))
        for candidate in run.candidates:
            existing = connection.execute(
                "SELECT run_id FROM candidates WHERE candidate_id = ?",
                (candidate.candidate_id,),
            ).fetchone()
            if existing is not None and existing["run_id"] != run.run_id:
                raise AcquisitionStoreConflictError("candidate id is already owned by another run")
            connection.execute(
                "INSERT INTO candidates(candidate_id, run_id, project_id, semantic_hash, raw_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    candidate.candidate_id,
                    candidate.run_id,
                    candidate.project_id,
                    semantic_digest(candidate),
                    candidate.model_dump_json(),
                    _iso(candidate.created_at),
                    _iso(candidate.updated_at),
                ),
            )

    def _save_record_transaction(
        self,
        *,
        table: str,
        id_column: str,
        record_id: str,
        project_id: str,
        status: str,
        record: _RecordT,
        expected_version: int | None,
        model: type[_RecordT],
        label: str,
    ) -> _RecordT:
        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            stored = self._save_versioned_record(
                connection,
                table=table,
                id_column=id_column,
                record_id=record_id,
                project_id=project_id,
                status=status,
                record=record,
                expected_version=expected_version,
            )
            connection.commit()
            return self._load_model(stored.model_dump_json(), model, label)
        except AcquisitionStoreError:
            connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise AcquisitionStoreConflictError(f"{label} conflicts with existing state") from exc
        except sqlite3.Error as exc:
            connection.rollback()
            raise AcquisitionStoreError(f"{label} transaction failed") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _save_versioned_record(
        self,
        connection: sqlite3.Connection,
        *,
        table: str,
        id_column: str,
        record_id: str,
        project_id: str,
        status: str,
        record: _RecordT,
        expected_version: int | None,
    ) -> _RecordT:
        _require_table(table, id_column)
        row = connection.execute(
            f"SELECT version, semantic_hash, raw_json FROM {table} WHERE {id_column} = ?",
            (record_id,),
        ).fetchone()
        digest = semantic_digest(record)
        if row is None:
            if expected_version is not None:
                raise AcquisitionStoreConflictError("record disappeared before compare-and-swap")
            version = int(getattr(record, "version", 1))
            connection.execute(
                f"INSERT INTO {table}({id_column}, project_id, status, version, semantic_hash, raw_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record_id,
                    project_id,
                    status,
                    version,
                    digest,
                    record.model_dump_json(),
                    _record_created_at(record),
                    _record_updated_at(record),
                ),
            )
            return record
        if expected_version is None:
            if row["semantic_hash"] == digest:
                return self._load_model(row["raw_json"], type(record), "record")
            raise AcquisitionStoreConflictError("stable record id was reused for different data")
        return self._update_existing_record(
            connection,
            table=table,
            id_column=id_column,
            record_id=record_id,
            project_id=project_id,
            status=status,
            record=record,
            expected_version=expected_version,
        )

    def _update_existing_record(
        self,
        connection: sqlite3.Connection,
        *,
        table: str,
        id_column: str,
        record_id: str,
        project_id: str,
        status: str,
        record: _RecordT,
        expected_version: int,
    ) -> _RecordT:
        _require_table(table, id_column)
        next_version = int(getattr(record, "version", expected_version + 1))
        if next_version != expected_version + 1:
            raise AcquisitionStoreConflictError("replacement version must increment by one")
        cursor = connection.execute(
            f"UPDATE {table} SET project_id = ?, status = ?, version = ?, semantic_hash = ?, "
            f"raw_json = ?, updated_at = ? WHERE {id_column} = ? AND version = ?",
            (
                project_id,
                status,
                next_version,
                semantic_digest(record),
                record.model_dump_json(),
                _record_updated_at(record),
                record_id,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            raise AcquisitionStoreConflictError("record changed before compare-and-swap")
        return record

    def _get_record(
        self,
        table: str,
        id_column: str,
        record_id: str,
        model: type[_RecordT],
        label: str,
    ) -> _RecordT | None:
        _require_table(table, id_column)
        normalized_id = _normalize_identifier(record_id, id_column)
        with closing(self._open_or_raise()) as connection:
            row = connection.execute(
                f"SELECT raw_json FROM {table} WHERE {id_column} = ?",
                (normalized_id,),
            ).fetchone()
        if row is None:
            return None
        return self._load_model(row["raw_json"], model, label)

    @staticmethod
    def _load_model(raw_json: str, model: type[_RecordT], label: str) -> _RecordT:
        try:
            raw = json.loads(raw_json)
            return model.model_validate(raw)
        except (json.JSONDecodeError, TypeError, ValidationError, ValueError) as exc:
            raise AcquisitionStoreCorruptionError(f"persisted {label} is invalid") from exc

    def _open_or_raise(self, *, initialize: bool = False) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            return connection
        except sqlite3.Error as exc:
            action = "initialize" if initialize else "open"
            raise AcquisitionStoreError(f"unable to {action} acquisition store") from exc


_TABLE_ID_COLUMNS = {
    "search_runs": "run_id",
    "candidates": "candidate_id",
    "download_jobs": "job_id",
    "human_gates": "gate_id",
    "validated_artifacts": "artifact_id",
    "import_receipts": "receipt_id",
}


def _require_table(table: str, id_column: str) -> None:
    if _TABLE_ID_COLUMNS.get(table) != id_column:
        raise ValueError("unsupported acquisition table")


def _normalize_identifier(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 256 or not all(
        character.isalnum() or character in "._:@+-" for character in normalized
    ):
        raise ValueError(f"{field_name} has an unsupported identifier shape")
    return normalized


def _validate_limit(limit: int) -> int:
    bounded = int(limit)
    if bounded < 1 or bounded > MAX_LIST_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIST_LIMIT}")
    return bounded


def _download_attempt_id(job_id: str, ordinal: int) -> str:
    """Return the canonical id for one download invocation ordinal."""

    encoded = f"{job_id}\0download\0{ordinal}".encode("utf-8")
    return f"attempt_{hashlib.sha256(encoded).hexdigest()[:24]}"


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _record_created_at(record: BaseModel) -> str:
    value = getattr(record, "created_at", None) or getattr(record, "validated_at", None)
    if not isinstance(value, datetime):
        value = utc_now()
    return _iso(value)


def _record_updated_at(record: BaseModel) -> str:
    value = getattr(record, "updated_at", None) or getattr(record, "validated_at", None)
    if not isinstance(value, datetime):
        value = utc_now()
    return _iso(value)
