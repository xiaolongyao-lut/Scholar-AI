"""Application service for explicit, compliant literature acquisition."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol

import httpx

from .downloader import (
    ControlProbe,
    DownloadCancelled,
    DownloadHumanGateRequired,
    DownloadPaused,
    DownloadPolicyError,
    DownloadTransferError,
    Resolver,
    download_validated_pdf,
    resolve_public_addresses,
    validate_download_destination,
)
from .models import (
    AcquisitionAttempt,
    AcquisitionAttemptOutcome,
    AcquisitionAttemptStage,
    AccessEvidence,
    AccessRoute,
    ArtifactPromotionProof,
    ArtifactPromotionState,
    CandidateManifest,
    CandidateVersionRelation,
    DownloadJob,
    DownloadJobStatus,
    GateStatus,
    HumanAccessGate,
    IdentityDecisionOutcome,
    IdentityMatchMethod,
    IdentityMergeReceipt,
    ImportReceipt,
    ImportPublicationEvidence,
    ImportPublicationState,
    ImportStatus,
    PdfCandidate,
    PdfValidationProvenance,
    SearchQuery,
    SearchRun,
    SearchRunStatus,
    SourceError,
    SourcePolicy,
    ValidatedArtifact,
    build_explicit_version_relation,
    candidate_identity_evidence,
    candidate_identity_match,
    merge_candidate_manifests,
    utc_now,
)
from .source_registry import (
    SourceAdapter,
    SourceAdapterError,
    SourceHumanGateRequired,
    SourceRegistry,
)
from .sources.arxiv import ArxivSourceAdapter
from .store import (
    AcquisitionStore,
    AcquisitionStoreConflictError,
    AcquisitionStoreError,
)
from .validator import (
    DEFAULT_MAX_PDF_BYTES,
    PDF_PARSER_ID,
    PDF_PARSER_VERSION,
    PDF_VALIDATION_CHECKS,
    PDF_VALIDATOR_ID,
    PDF_VALIDATOR_VERSION,
    PdfValidationResult,
    validate_pdf_file,
)


MAX_DOWNLOAD_ATTEMPTS = 10


class AcquisitionServiceError(RuntimeError):
    """Bounded application-layer acquisition failure."""

    def __init__(self, code: str, message: str) -> None:
        """Initialize a stable error code and user-safe message."""

        super().__init__(message)
        self.code = str(code or "acquisition_error")[:80]
        self.safe_message = str(message or "Acquisition failed").replace("\n", " ")[:500]


class AcquisitionNotFoundError(AcquisitionServiceError):
    """Requested project or acquisition record does not exist."""


class AcquisitionConflictError(AcquisitionServiceError):
    """Requested transition conflicts with durable state."""


class AcquisitionPolicyError(AcquisitionServiceError):
    """Requested action does not satisfy the access policy."""


class ProjectPathResolver(Protocol):
    """Resolve a project-local path using the canonical workspace layout."""

    def __call__(self, project_id: str, *parts: str) -> Path:
        """Return a path below one project's workspace root."""


class ValidatedPdfIngestor(Protocol):
    """Existing-project PDF ingestion seam shared with resource uploads."""

    def __call__(
        self,
        project_id: str,
        source_path: Path,
        *,
        expected_sha256: str,
        expected_size: int,
    ) -> Awaitable[Mapping[str, object]]:
        """Queue or complete ingestion of an already validated local PDF."""


class MaterialPublicationVerifier(Protocol):
    """Verify that one imported material is fully published and indexed."""

    def __call__(
        self,
        project_id: str,
        material_id: str,
        *,
        expected_source_fingerprint: str,
        expected_source_size: int,
    ) -> ImportPublicationEvidence:
        """Return strict publication evidence or raise a bounded integrity error."""


class RuntimeJobRecord(Protocol):
    """Minimum persisted runtime job fields needed for import reconciliation."""

    job_id: str
    session_id: str
    status: object
    error: str | None


class ImportRuntimeReader(Protocol):
    """Read persisted runtime job and material-task state without mutation."""

    def get_job(self, job_id: str) -> RuntimeJobRecord | None:
        """Return one runtime job or None when it is not available."""

    def get_material_processing_task(self, job_id: str) -> Mapping[str, object] | None:
        """Return the latest persisted material-processing task, if present."""


def _default_project_path(project_id: str, *parts: str) -> Path:
    from project_paths import project_data_path

    return project_data_path(project_id, *parts)


def _default_project_validator(project_id: str) -> None:
    from writing_resources import get_writing_resource_store

    if get_writing_resource_store().get_project(project_id) is None:
        raise AcquisitionNotFoundError("project_not_found", f"Project not found: {project_id}")


async def _default_ingest_pdf(
    project_id: str,
    source_path: Path,
    *,
    expected_sha256: str,
    expected_size: int,
) -> Mapping[str, object]:
    from routers.resources_router import ingest_validated_pdf_path

    return await ingest_validated_pdf_path(
        project_id,
        source_path,
        expected_sha256=expected_sha256,
        expected_size=expected_size,
    )


def _default_verify_material_publication(
    project_id: str,
    material_id: str,
    *,
    expected_source_fingerprint: str,
    expected_source_size: int,
) -> ImportPublicationEvidence:
    from routers.resources_router import verify_material_publication

    return verify_material_publication(
        project_id,
        material_id,
        expected_source_fingerprint=expected_source_fingerprint,
        expected_source_size=expected_source_size,
    )


class LiteratureAcquisitionService:
    """Coordinate search, download, validation, gates, and material ingestion."""

    def __init__(
        self,
        store: AcquisitionStore,
        *,
        registry: SourceRegistry | None = None,
        project_path: ProjectPathResolver = _default_project_path,
        validate_project: Callable[[str], None] = _default_project_validator,
        ingest_pdf: ValidatedPdfIngestor = _default_ingest_pdf,
        verify_material_publication: MaterialPublicationVerifier = _default_verify_material_publication,
        download_client: httpx.AsyncClient | None = None,
        resolver: Resolver = resolve_public_addresses,
        runtime_reader: ImportRuntimeReader | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Initialize the service with injectable network and project adapters.

        Args:
            store: Durable acquisition state store.
            registry: Explicit source adapter registry; defaults to arXiv only.
            project_path: Canonical project-local path resolver.
            validate_project: Existing-project existence guard.
            ingest_pdf: Existing resource ingestion seam.
            verify_material_publication: Strict resource-owned publication
                inspector used before a receipt may become completed.
            download_client: Optional client used by fixture tests.
            resolver: DNS resolver used for public-unicast enforcement.
            runtime_reader: Optional persisted runtime read adapter used to
                reconcile queued import receipts.
            monotonic: Monotonic clock used by per-source rate enforcement.
            sleep: Awaitable delay function used by per-source rate enforcement.
        """

        if not isinstance(store, AcquisitionStore):
            raise TypeError("store must be AcquisitionStore")
        self.store = store
        self.registry = registry or SourceRegistry((ArxivSourceAdapter(),))
        self._project_path = project_path
        self._validate_project = validate_project
        self._ingest_pdf = ingest_pdf
        self._verify_material_publication = verify_material_publication
        self._download_client = download_client
        self._resolver = resolver
        self._runtime_reader = runtime_reader
        self._monotonic = monotonic
        self._sleep = sleep
        self._source_search_locks: dict[str, asyncio.Lock] = {}
        self._source_last_started: dict[str, float] = {}

    async def search(self, query: SearchQuery) -> SearchRun:
        """Run one explicit bounded search and persist its normalized manifest.

        Args:
            query: Strict project-scoped query and requested source ids.

        Returns:
            Terminal search run with merged candidates and bounded source errors.
        """

        if not isinstance(query, SearchQuery):
            raise TypeError("query must be SearchQuery")
        self._validate_project(query.project_id)
        run_id = f"run_{secrets.token_hex(12)}"
        created_at = utc_now()
        running = SearchRun(
            run_id=run_id,
            query=query,
            status=SearchRunStatus.RUNNING,
            requested_sources=query.sources,
            created_at=created_at,
            updated_at=created_at,
        )
        self.store.save_search_run(running)

        attempted: list[str] = []
        candidates: list[CandidateManifest] = []
        identity_receipts: list[IdentityMergeReceipt] = []
        errors: list[SourceError] = []
        for ordinal, source_id in enumerate(query.sources, start=1):
            attempted.append(source_id)
            attempt_started_at = utc_now()
            try:
                adapter = self.registry.get(source_id)
                source_query = SearchQuery.model_validate(
                    {
                        **query.model_dump(mode="python"),
                        "sources": (source_id,),
                        "max_results": min(query.max_results, adapter.policy.max_results_per_query),
                    }
                )
                incoming = await self._search_source(adapter, source_query, run_id=run_id)
                for candidate in incoming:
                    self._merge_candidate(
                        candidates,
                        candidate,
                        identity_receipts,
                        retain_new=len(candidates) < query.max_results,
                    )
                self._append_search_attempt(
                    run=running,
                    source_id=source_id,
                    ordinal=ordinal,
                    outcome=AcquisitionAttemptOutcome.SUCCEEDED,
                    started_at=attempt_started_at,
                    result_count=len(incoming),
                )
            except SourceHumanGateRequired as exc:
                gate = self._persist_search_gate(
                    run_id=run_id,
                    query=query,
                    source_id=source_id,
                    gate_type=exc.gate_type,
                    url=exc.url,
                    message=exc.safe_message,
                )
                errors.append(
                    SourceError(
                        source_id=source_id,
                        code="human_gate_required",
                        message=exc.safe_message,
                    )
                )
                self._append_search_attempt(
                    run=running,
                    source_id=source_id,
                    ordinal=ordinal,
                    outcome=AcquisitionAttemptOutcome.HUMAN_REQUIRED,
                    started_at=attempt_started_at,
                    error_class=exc.code,
                    error_message=exc.safe_message,
                    gate_id=gate.gate_id,
                    next_action=gate.next_action,
                )
            except SourceAdapterError as exc:
                errors.append(SourceError(source_id=source_id, code=exc.code, message=exc.safe_message))
                self._append_search_attempt(
                    run=running,
                    source_id=source_id,
                    ordinal=ordinal,
                    outcome=AcquisitionAttemptOutcome.FAILED,
                    started_at=attempt_started_at,
                    error_class=exc.code,
                    error_message=exc.safe_message,
                    retryable=exc.code in {"transport_error", "http_429", "http_503"},
                )
            except KeyError:
                errors.append(
                    SourceError(
                        source_id=source_id,
                        code="source_unavailable",
                        message=f"Source adapter is unavailable: {source_id}",
                    )
                )
                self._append_search_attempt(
                    run=running,
                    source_id=source_id,
                    ordinal=ordinal,
                    outcome=AcquisitionAttemptOutcome.FAILED,
                    started_at=attempt_started_at,
                    error_class="source_unavailable",
                    error_message=f"Source adapter is unavailable: {source_id}",
                )

        successful_sources = len(attempted) - len(errors)
        if errors and successful_sources == 0:
            status = SearchRunStatus.FAILED
        elif errors:
            status = SearchRunStatus.PARTIAL
        else:
            status = SearchRunStatus.COMPLETED
        completed_at = utc_now()
        version_relations = self._build_candidate_version_relations(
            candidates,
            created_at=completed_at,
        )
        terminal = SearchRun.model_validate(
            running.model_copy(
                update={
                    "status": status,
                    "attempted_sources": tuple(attempted),
                    "candidates": tuple(candidates),
                    "source_errors": tuple(errors),
                    "version": running.version + 1,
                    "updated_at": completed_at,
                    "completed_at": completed_at,
                }
            ).model_dump(mode="python")
        )
        return self.store.save_search_run(
            terminal,
            expected_version=running.version,
            identity_receipts=identity_receipts,
            version_relations=version_relations,
        )

    def list_source_policies(self) -> tuple[SourcePolicy, ...]:
        """Return enabled source policies without starting external work."""

        return self.registry.policies()

    def get_search_run(self, run_id: str) -> SearchRun:
        """Return one persisted search run or a bounded not-found error."""

        run = self.store.get_search_run(run_id)
        if run is None:
            raise AcquisitionNotFoundError("search_run_not_found", f"Search run not found: {run_id}")
        return run

    def list_identity_merge_receipts(
        self,
        run_id: str,
        *,
        limit: int = 100,
    ) -> tuple[IdentityMergeReceipt, ...]:
        """Read a bounded identity ledger without repeating source work."""

        self.get_search_run(run_id)
        return self.store.list_identity_merge_receipts(run_id, limit=limit)

    def list_candidate_version_relations(
        self,
        run_id: str,
        *,
        limit: int = 100,
    ) -> tuple[CandidateVersionRelation, ...]:
        """Read bounded explicit version edges without inferring new relations."""

        self.get_search_run(run_id)
        return self.store.list_candidate_version_relations(run_id, limit=limit)

    def get_download_job(self, job_id: str) -> DownloadJob:
        """Return one persisted download job or a bounded not-found error."""

        job = self.store.get_download_job(job_id)
        if job is None:
            raise AcquisitionNotFoundError("download_job_not_found", f"Download job not found: {job_id}")
        return job

    def get_gate(self, gate_id: str) -> HumanAccessGate:
        """Return one persisted human gate or a bounded not-found error."""

        gate = self.store.get_gate(gate_id)
        if gate is None:
            raise AcquisitionNotFoundError("access_gate_not_found", f"Access gate not found: {gate_id}")
        return gate

    def get_artifact(self, artifact_id: str) -> ValidatedArtifact:
        """Return one validated artifact or a bounded not-found error."""

        artifact = self.store.get_artifact(artifact_id)
        if artifact is None:
            raise AcquisitionNotFoundError(
                "validated_artifact_not_found",
                f"Validated artifact not found: {artifact_id}",
            )
        return artifact

    def get_import_receipt(self, receipt_id: str) -> ImportReceipt:
        """Return one durable receipt after projecting available terminal state."""

        receipt = self.store.get_import_receipt(receipt_id)
        if receipt is None:
            raise AcquisitionNotFoundError("import_receipt_not_found", f"Import receipt not found: {receipt_id}")
        return self._reconcile_import_receipt(receipt)

    def reconcile_import_receipts(self, *, limit: int = 500) -> tuple[ImportReceipt, ...]:
        """CAS-project pending receipts from persisted runtime state.

        Missing or non-terminal runtime records remain queued because neither
        condition proves that material processing failed. The method performs
        read-only runtime inspection and never starts or repeats ingestion.

        Args:
            limit: Maximum number of pending receipts to reconcile.

        Returns:
            Stable-order receipts after each available reconciliation attempt.
        """

        pending = self.store.list_import_receipts(
            statuses=(ImportStatus.QUEUED, ImportStatus.COMPLETED, ImportStatus.DUPLICATE),
            publication_states=(ImportPublicationState.PENDING,),
            limit=limit,
        )
        return tuple(self._reconcile_import_receipt(receipt) for receipt in pending)

    def list_download_jobs(
        self,
        *,
        project_id: str | None = None,
        statuses: Sequence[DownloadJobStatus] = (),
        limit: int = 100,
    ) -> tuple[DownloadJob, ...]:
        """Return bounded persisted download jobs without running workers."""

        return self.store.list_download_jobs(
            project_id=project_id,
            statuses=statuses,
            limit=limit,
        )

    def list_gates(
        self,
        *,
        project_id: str | None = None,
        statuses: Sequence[GateStatus] = (),
        limit: int = 100,
    ) -> tuple[HumanAccessGate, ...]:
        """Return bounded user-owned access gates without resolving them."""

        return self.store.list_gates(
            project_id=project_id,
            statuses=statuses,
            limit=limit,
        )

    def queue_download(
        self,
        *,
        project_id: str,
        candidate_id: str,
        access_evidence_id: str,
        max_bytes: int = DEFAULT_MAX_PDF_BYTES,
    ) -> DownloadJob:
        """Create an idempotent download job from exact OA access evidence."""

        self._validate_project(project_id)
        candidate, pdf, policy = self._authorize_candidate_download(
            project_id=project_id,
            candidate_id=candidate_id,
            access_evidence_id=access_evidence_id,
        )
        if max_bytes < 4096 or max_bytes > DEFAULT_MAX_PDF_BYTES:
            raise AcquisitionPolicyError(
                "invalid_max_bytes",
                f"max_bytes must be between 4096 and {DEFAULT_MAX_PDF_BYTES}",
            )
        digest = _stable_digest(candidate.candidate_id, pdf.access_evidence.evidence_id)
        job_id = f"download_{digest[:24]}"
        existing = self.store.get_download_job(job_id)
        if existing is not None:
            return existing
        job = DownloadJob(
            job_id=job_id,
            project_id=project_id,
            candidate_id=candidate.candidate_id,
            access_evidence_id=pdf.access_evidence.evidence_id,
            source_platform=policy.source_id,
            source_url=pdf.pdf_url,
            artifact_path=f"source_files/acquired_{digest[:24]}.pdf",
            max_bytes=max_bytes,
        )
        return self.store.save_download_job(job)

    async def run_download(self, job_id: str) -> DownloadJob:
        """Run or explicitly retry one queued/paused/failed download job."""

        job = self._require_download_job(job_id)
        if job.status is DownloadJobStatus.COMPLETED:
            return job
        if job.status not in {
            DownloadJobStatus.QUEUED,
            DownloadJobStatus.PAUSED,
            DownloadJobStatus.FAILED,
        }:
            raise AcquisitionConflictError(
                "download_not_runnable",
                f"Download cannot run from status {job.status.value}",
            )
        if job.attempts >= MAX_DOWNLOAD_ATTEMPTS:
            raise AcquisitionConflictError("attempt_limit", "Download attempt limit reached")
        _, pdf_candidate, policy = self._authorize_candidate_download(
            project_id=job.project_id,
            candidate_id=job.candidate_id,
            access_evidence_id=job.access_evidence_id,
        )
        attempt_started_at = utc_now()
        running = self.store.transition_download_job(
            job.job_id,
            expected_version=job.version,
            from_statuses=(job.status,),
            to_status=DownloadJobStatus.RUNNING,
            attempts=job.attempts + 1,
            bytes_downloaded=job.bytes_downloaded,
        )
        project_root = self._project_path(running.project_id).resolve()
        destination = validate_download_destination(
            project_root.joinpath(*Path(running.artifact_path).parts),
            project_root,
        )
        attempt_id = _download_attempt_id(running)
        promotion_proof: ArtifactPromotionProof | None = None

        def control_probe() -> str:
            latest = self.store.get_download_job(running.job_id)
            if latest is not None and latest.status is DownloadJobStatus.PAUSED:
                return "pause"
            if latest is not None and latest.status is DownloadJobStatus.CANCELLED:
                return "cancel"
            return "continue"

        def record_promotion(final_url: str, validation: PdfValidationResult) -> None:
            nonlocal promotion_proof
            existing_proof = self.store.get_job_artifact_promotion_proof(running.job_id)
            if existing_proof is not None:
                if existing_proof.state is not ArtifactPromotionState.PREPARED:
                    raise DownloadTransferError(
                        "artifact_proof_state_invalid",
                        "Active download has a non-prepared promotion proof",
                    )
                self._validate_promotion_proof(
                    existing_proof,
                    running,
                    pdf_candidate.access_evidence,
                    validation,
                )
                promotion_proof = existing_proof
                return
            artifact_id = f"artifact_{_stable_digest(running.job_id, validation.sha256)[:24]}"
            validated_at = utc_now()
            proof = ArtifactPromotionProof(
                proof_id=f"proof_{_stable_digest(artifact_id, attempt_id)[:24]}",
                artifact_id=artifact_id,
                job_id=running.job_id,
                attempt_id=attempt_id,
                project_id=running.project_id,
                candidate_id=running.candidate_id,
                source_platform=running.source_platform,
                source_url=running.source_url,
                final_url=final_url,
                access_evidence=pdf_candidate.access_evidence,
                relative_path=running.artifact_path,
                size_bytes=validation.size_bytes,
                sha256=validation.sha256,
                page_count=validation.page_count,
                validation=PdfValidationProvenance(
                    validator_id=PDF_VALIDATOR_ID,
                    validator_version=PDF_VALIDATOR_VERSION,
                    parser_id=PDF_PARSER_ID,
                    parser_version=PDF_PARSER_VERSION,
                    checks=PDF_VALIDATION_CHECKS,
                    validated_at=validated_at,
                ),
                prepared_at=utc_now(),
            )
            promotion_proof = self.store.save_artifact_promotion_proof(proof)

        try:
            if destination.exists():
                promotion_proof = self.store.get_job_artifact_promotion_proof(running.job_id)
                if promotion_proof is None:
                    raise DownloadTransferError(
                        "artifact_proof_missing",
                        "Existing PDF has no durable promotion proof",
                        bytes_downloaded=destination.stat().st_size,
                    )
                if promotion_proof.state is not ArtifactPromotionState.PREPARED:
                    raise DownloadTransferError(
                        "artifact_proof_state_invalid",
                        "Active download has a non-prepared promotion proof",
                        bytes_downloaded=destination.stat().st_size,
                    )
                validation = validate_pdf_file(destination, max_bytes=running.max_bytes)
                self._validate_promotion_proof(
                    promotion_proof,
                    running,
                    pdf_candidate.access_evidence,
                    validation,
                )
            else:
                downloaded = await download_validated_pdf(
                    source_url=running.source_url,
                    policy=policy,
                    destination=destination,
                    project_root=project_root,
                    client=self._download_client,
                    resolver=self._resolver,
                    control_probe=control_probe,
                    record_promotion=record_promotion,
                    max_bytes=running.max_bytes,
                )
                validation = downloaded.validation
                if promotion_proof is None:
                    raise DownloadTransferError(
                        "artifact_proof_missing",
                        "PDF promotion completed without durable proof",
                        bytes_downloaded=validation.size_bytes,
                    )
            validating = self.store.transition_download_job(
                running.job_id,
                expected_version=running.version,
                from_statuses=(DownloadJobStatus.RUNNING,),
                to_status=DownloadJobStatus.VALIDATING,
                bytes_downloaded=validation.size_bytes,
            )
            artifact = ValidatedArtifact(
                artifact_id=promotion_proof.artifact_id,
                job_id=validating.job_id,
                project_id=validating.project_id,
                candidate_id=validating.candidate_id,
                relative_path=validating.artifact_path,
                size_bytes=validation.size_bytes,
                sha256=validation.sha256,
                page_count=validation.page_count,
            )
            success_attempt = self._build_download_attempt(
                running,
                outcome=AcquisitionAttemptOutcome.SUCCEEDED,
                started_at=attempt_started_at,
            )
            completed = self.store.complete_download_job(
                artifact,
                promotion_proof,
                expected_job_version=validating.version,
                attempt=success_attempt,
            )
            return completed
        except AcquisitionStoreConflictError as exc:
            latest = self._require_download_job(running.job_id)
            if latest.status is DownloadJobStatus.CANCELLED:
                return self._cleanup_cancelled_download(latest)
            if latest.status is DownloadJobStatus.PAUSED:
                return latest
            if latest.status is DownloadJobStatus.COMPLETED:
                return latest
            self._append_download_attempt(
                running,
                outcome=AcquisitionAttemptOutcome.FAILED,
                started_at=attempt_started_at,
                error_class="download_state_conflict",
                error_message=str(exc),
            )
            raise AcquisitionConflictError("download_state_conflict", str(exc)) from exc
        except DownloadPaused as exc:
            attempt = self._build_download_attempt(
                running,
                outcome=AcquisitionAttemptOutcome.PAUSED,
                started_at=attempt_started_at,
            )
            return self._settle_control_state(
                running,
                DownloadJobStatus.PAUSED,
                exc.bytes_downloaded,
                attempt=attempt,
            )
        except DownloadCancelled as exc:
            attempt = self._build_download_attempt(
                running,
                outcome=AcquisitionAttemptOutcome.CANCELLED,
                started_at=attempt_started_at,
            )
            return self._settle_control_state(
                running,
                DownloadJobStatus.CANCELLED,
                exc.bytes_downloaded,
                attempt=attempt,
            )
        except DownloadHumanGateRequired as exc:
            return self._open_download_gate(running, exc, started_at=attempt_started_at)
        except DownloadPolicyError as exc:
            attempt = self._build_download_attempt(
                running,
                outcome=AcquisitionAttemptOutcome.FAILED,
                started_at=attempt_started_at,
                error_class="policy_error",
                error_message=str(exc),
            )
            return self._fail_running_download(
                running,
                "policy_error",
                str(exc),
                running.bytes_downloaded,
                attempt=attempt,
            )
        except DownloadTransferError as exc:
            attempt = self._build_download_attempt(
                running,
                outcome=AcquisitionAttemptOutcome.FAILED,
                started_at=attempt_started_at,
                error_class=exc.code,
                error_message=exc.safe_message,
                retryable=exc.code not in {"artifact_proof_missing", "artifact_proof_mismatch"},
            )
            return self._fail_running_download(
                running,
                exc.code,
                exc.safe_message,
                exc.bytes_downloaded,
                attempt=attempt,
            )
        except (OSError, ValueError) as exc:
            attempt = self._build_download_attempt(
                running,
                outcome=AcquisitionAttemptOutcome.FAILED,
                started_at=attempt_started_at,
                error_class="download_failed",
                error_message=str(exc),
            )
            return self._fail_running_download(
                running,
                "download_failed",
                str(exc),
                running.bytes_downloaded,
                attempt=attempt,
            )

    def pause_download(self, job_id: str) -> DownloadJob:
        """Pause a queued or running job while preserving its ``.part`` file."""

        job = self._require_download_job(job_id)
        if job.status is DownloadJobStatus.PAUSED:
            return job
        if job.status not in {DownloadJobStatus.QUEUED, DownloadJobStatus.RUNNING}:
            raise AcquisitionConflictError("download_not_pauseable", "Download cannot be paused")
        if job.status is DownloadJobStatus.RUNNING:
            attempt = self._build_download_attempt(
                job,
                outcome=AcquisitionAttemptOutcome.PAUSED,
                started_at=job.started_at or job.updated_at,
            )
            settled, _, _ = self.store.settle_download_job(
                job.job_id,
                expected_version=job.version,
                from_statuses=(DownloadJobStatus.RUNNING,),
                to_status=DownloadJobStatus.PAUSED,
                attempt=attempt,
                bytes_downloaded=job.bytes_downloaded,
            )
            return settled
        return self.store.transition_download_job(
            job.job_id,
            expected_version=job.version,
            from_statuses=(job.status,),
            to_status=DownloadJobStatus.PAUSED,
            bytes_downloaded=job.bytes_downloaded,
        )

    def resume_download(self, job_id: str) -> DownloadJob:
        """Requeue one paused job without starting network work."""

        job = self._require_download_job(job_id)
        if job.status is DownloadJobStatus.QUEUED:
            return job
        if job.status is not DownloadJobStatus.PAUSED:
            raise AcquisitionConflictError("download_not_resumable", "Only paused downloads can be resumed")
        return self.store.transition_download_job(
            job.job_id,
            expected_version=job.version,
            from_statuses=(DownloadJobStatus.PAUSED,),
            to_status=DownloadJobStatus.QUEUED,
            bytes_downloaded=job.bytes_downloaded,
        )

    def cancel_download(self, job_id: str) -> DownloadJob:
        """Cancel a non-completed job and durably finish its local cleanup.

        Cancellation first wins the job compare-and-swap, then removes the
        adjacent final/partial files and invalidates any prepared promotion
        proof. A filesystem or persistence failure remains visible on the
        cancelled job so a later call can retry cleanup.

        Args:
            job_id: Stable download-job identifier.

        Returns:
            Persisted cancelled job after files and prepared proof are absent.

        Raises:
            AcquisitionNotFoundError: If the job does not exist.
            AcquisitionConflictError: If the job completed, concurrent state
                cannot converge, or cleanup remains incomplete.
        """

        cancelled = self._transition_download_to_cancelled(job_id)
        return self._cleanup_cancelled_download(cancelled)

    def resolve_gate(self, gate_id: str) -> tuple[HumanAccessGate, DownloadJob | None]:
        """Resolve a user-owned gate and requeue its download, without running it."""

        gate = self.store.get_gate(gate_id)
        if gate is None:
            raise AcquisitionNotFoundError("gate_not_found", f"Gate not found: {gate_id}")
        related_job: DownloadJob | None = None
        if gate.job_id is not None:
            related_job = self._require_download_job(gate.job_id)
            if (
                related_job.status is not DownloadJobStatus.HUMAN_REQUIRED
                or related_job.gate_id != gate.gate_id
            ):
                raise AcquisitionConflictError("gate_job_mismatch", "Gate no longer owns the download job")
        try:
            if related_job is not None:
                resolved, related_job = self.store.resolve_gate_and_requeue_download(
                    gate.gate_id,
                    expected_gate_version=gate.version,
                    expected_job_version=related_job.version,
                )
            else:
                resolved = self.store.resolve_gate(gate.gate_id, expected_version=gate.version)
            return resolved, related_job
        except AcquisitionStoreConflictError as exc:
            raise AcquisitionConflictError("gate_conflict", str(exc)) from exc

    async def import_artifact(self, artifact_id: str) -> ImportReceipt:
        """Revalidate and ingest one artifact into its existing project.

        Args:
            artifact_id: Stable identifier of a promoted validated artifact.

        Returns:
            Durable import receipt. Synchronous ingestion is persisted as
            publication-pending before verification and may remain pending
            until a later reconciliation pass.

        Raises:
            AcquisitionNotFoundError: If the artifact does not exist.
            AcquisitionPolicyError: If its stored path escapes the project.
            AcquisitionConflictError: If durable proof, bytes, or ingest
                identity conflicts with persisted state.
        """

        artifact = self.store.get_artifact(artifact_id)
        if artifact is None:
            raise AcquisitionNotFoundError("artifact_not_found", f"Artifact not found: {artifact_id}")
        promotion_proof = self.store.get_artifact_promotion_proof(artifact.artifact_id)
        if promotion_proof is None:
            raise AcquisitionConflictError(
                "artifact_proof_missing",
                "Validated artifact has no durable promotion proof",
            )
        if promotion_proof.state is not ArtifactPromotionState.PROMOTED:
            raise AcquisitionConflictError(
                "artifact_proof_incomplete",
                "Validated artifact promotion was not atomically confirmed",
            )
        job = self._require_download_job(artifact.job_id)
        _, pdf_candidate, _ = self._authorize_candidate_download(
            project_id=artifact.project_id,
            candidate_id=artifact.candidate_id,
            access_evidence_id=job.access_evidence_id,
        )
        self._validate_project(artifact.project_id)
        receipt_id = f"import_{_stable_digest(artifact.artifact_id)[:24]}"
        existing = self.store.get_import_receipt(receipt_id)
        if existing is not None:
            return self._reconcile_import_receipt(existing)

        project_root = self._project_path(artifact.project_id).resolve()
        source_path = project_root.joinpath(*Path(artifact.relative_path).parts).resolve()
        if project_root not in source_path.parents:
            raise AcquisitionPolicyError("artifact_path_escape", "Artifact path escaped its project")
        validation = validate_pdf_file(source_path, max_bytes=max(artifact.size_bytes, 4096))
        if validation.size_bytes != artifact.size_bytes or validation.sha256 != artifact.sha256:
            raise AcquisitionConflictError("artifact_integrity_failed", "Validated artifact integrity changed")
        self._validate_promotion_proof(
            promotion_proof,
            job,
            pdf_candidate.access_evidence,
            validation,
        )

        result = await self._ingest_pdf(
            artifact.project_id,
            source_path,
            expected_sha256=artifact.sha256,
            expected_size=artifact.size_bytes,
        )
        material_id = _required_result_text(result, "material_id")
        runtime_job_id = _optional_result_text(result, "job_id")
        runtime_session_id = _optional_result_text(result, "session_id")
        result_status = str(result.get("status") or "").strip().lower()
        if result_status == "duplicate":
            status = ImportStatus.DUPLICATE
        elif runtime_job_id is not None and runtime_session_id is not None:
            status = ImportStatus.QUEUED
        else:
            status = ImportStatus.COMPLETED
        pending_receipt = ImportReceipt(
            receipt_id=receipt_id,
            artifact_id=artifact.artifact_id,
            project_id=artifact.project_id,
            candidate_id=artifact.candidate_id,
            material_id=material_id,
            status=status,
            source_fingerprint=f"sha256:{artifact.sha256}",
            receipt_schema_version="scholar-ai-import-receipt/v2",
            publication_state=ImportPublicationState.PENDING,
            publication_evidence=None,
            runtime_session_id=runtime_session_id,
            runtime_job_id=runtime_job_id,
            open_url=str(result.get("open_url") or f"/workbench/paper/{material_id}"),
            error_message=(
                None
                if status is ImportStatus.QUEUED
                else "Material publication verification is pending"
            ),
        )
        try:
            saved = self.store.save_import_receipt(pending_receipt)
        except AcquisitionStoreConflictError:
            existing = self.store.get_import_receipt(receipt_id)
            if existing is None:
                raise AcquisitionConflictError(
                    "import_receipt_conflict",
                    "Import receipt changed before it could be persisted",
                )
            return self._reconcile_import_receipt(existing)
        if status is ImportStatus.QUEUED:
            return saved
        return self._reconcile_import_receipt(saved)

    def _reconcile_import_receipt(self, receipt: ImportReceipt) -> ImportReceipt:
        """Project one pending receipt using optimistic concurrency control."""

        if (
            receipt.status in {ImportStatus.COMPLETED, ImportStatus.DUPLICATE}
            and receipt.publication_state is ImportPublicationState.PENDING
        ):
            return self._reconcile_pending_publication(receipt)
        if receipt.status is not ImportStatus.QUEUED:
            return receipt
        projected_status, error_message = self._read_runtime_import_terminal(receipt)
        if projected_status is None:
            return receipt

        current = receipt
        for _attempt in range(2):
            publication_evidence: ImportPublicationEvidence | None = None
            publication_state = ImportPublicationState.FAILED
            projected_error = error_message
            if projected_status is ImportStatus.COMPLETED:
                artifact = self.store.get_artifact(current.artifact_id)
                if artifact is None:
                    return self._record_publication_pending(
                        current,
                        "Material publication verification is pending: validated artifact is unavailable",
                    )
                try:
                    publication_evidence = self._verify_published_material(
                        artifact=artifact,
                        material_id=current.material_id,
                    )
                except AcquisitionConflictError:
                    return self._record_publication_pending(
                        current,
                        "Material publication verification is pending",
                    )
                publication_state = ImportPublicationState.VERIFIED
                projected_error = None
            replacement_payload = current.model_dump()
            replacement_payload.update(
                {
                    "status": projected_status,
                    "receipt_schema_version": "scholar-ai-import-receipt/v2",
                    "publication_state": publication_state,
                    "publication_evidence": publication_evidence,
                    "error_message": projected_error,
                    "version": current.version + 1,
                    "updated_at": utc_now(),
                }
            )
            try:
                replacement = ImportReceipt.model_validate(replacement_payload)
            except ValueError:
                replacement_payload["error_message"] = (
                    "Runtime material ingestion failed"
                    if projected_status is ImportStatus.FAILED
                    else None
                )
                replacement = ImportReceipt.model_validate(replacement_payload)
            try:
                return self.store.save_import_receipt(replacement, expected_version=current.version)
            except AcquisitionStoreConflictError:
                latest = self.store.get_import_receipt(current.receipt_id)
                if latest is None:
                    raise AcquisitionConflictError(
                        "import_receipt_conflict",
                        "Import receipt disappeared during reconciliation",
                    )
                if latest.status is not ImportStatus.QUEUED:
                    return latest
                current = latest
        raise AcquisitionConflictError(
            "import_receipt_conflict",
            "Import receipt changed repeatedly during reconciliation",
        )

    def _reconcile_pending_publication(self, receipt: ImportReceipt) -> ImportReceipt:
        """Verify and CAS-upgrade a synchronously ingested pending receipt."""

        current = receipt
        for _attempt in range(3):
            artifact = self.store.get_artifact(current.artifact_id)
            if artifact is None:
                return self._record_publication_pending(
                    current,
                    "Material publication verification is pending: validated artifact is unavailable",
                )
            try:
                evidence = self._verify_published_material(
                    artifact=artifact,
                    material_id=current.material_id,
                )
            except AcquisitionConflictError:
                return self._record_publication_pending(
                    current,
                    "Material publication verification is pending",
                )
            replacement_payload = current.model_dump()
            replacement_payload.update(
                {
                    "receipt_schema_version": "scholar-ai-import-receipt/v2",
                    "publication_state": ImportPublicationState.VERIFIED,
                    "publication_evidence": evidence,
                    "error_message": None,
                    "version": current.version + 1,
                    "updated_at": utc_now(),
                }
            )
            verified = ImportReceipt.model_validate(replacement_payload)
            try:
                return self.store.save_import_receipt(
                    verified,
                    expected_version=current.version,
                )
            except AcquisitionStoreConflictError:
                latest = self.store.get_import_receipt(current.receipt_id)
                if latest is None:
                    raise AcquisitionConflictError(
                        "import_receipt_conflict",
                        "Import receipt disappeared during publication verification",
                    )
                if latest.publication_state is not ImportPublicationState.PENDING:
                    return latest
                current = latest
        raise AcquisitionConflictError(
            "import_receipt_conflict",
            "Import receipt changed repeatedly during publication verification",
        )

    def _record_publication_pending(
        self,
        receipt: ImportReceipt,
        message: str,
    ) -> ImportReceipt:
        """Persist one bounded pending marker without claiming completion."""

        if (
            receipt.receipt_schema_version == "scholar-ai-import-receipt/v2"
            and receipt.publication_state is ImportPublicationState.PENDING
            and receipt.error_message == message
        ):
            return receipt
        payload = receipt.model_dump()
        payload.update(
            {
                "receipt_schema_version": "scholar-ai-import-receipt/v2",
                "publication_state": ImportPublicationState.PENDING,
                "publication_evidence": None,
                "error_message": message,
                "version": receipt.version + 1,
                "updated_at": utc_now(),
            }
        )
        pending = ImportReceipt.model_validate(payload)
        try:
            return self.store.save_import_receipt(pending, expected_version=receipt.version)
        except AcquisitionStoreConflictError:
            latest = self.store.get_import_receipt(receipt.receipt_id)
            if latest is None:
                raise AcquisitionConflictError(
                    "import_receipt_conflict",
                    "Import receipt disappeared during publication verification",
                )
            return latest

    def _verify_published_material(
        self,
        *,
        artifact: ValidatedArtifact,
        material_id: str,
    ) -> ImportPublicationEvidence:
        """Return strict resource publication evidence bound to one artifact."""

        try:
            evidence = self._verify_material_publication(
                artifact.project_id,
                material_id,
                expected_source_fingerprint=f"sha256:{artifact.sha256}",
                expected_source_size=artifact.size_bytes,
            )
        except Exception as exc:
            raise AcquisitionConflictError(
                "material_publication_unverified",
                "Material publication integrity could not be verified",
            ) from exc
        if not isinstance(evidence, ImportPublicationEvidence):
            raise AcquisitionConflictError(
                "material_publication_unverified",
                "Material publication verifier returned an unsupported result",
            )
        if (
            evidence.project_id != artifact.project_id
            or evidence.material_id != material_id
            or evidence.source_fingerprint != f"sha256:{artifact.sha256}"
            or evidence.source_size_bytes != artifact.size_bytes
        ):
            raise AcquisitionConflictError(
                "material_publication_unverified",
                "Material publication evidence does not match the validated artifact",
            )
        return evidence

    def _read_runtime_import_terminal(
        self,
        receipt: ImportReceipt,
    ) -> tuple[ImportStatus | None, str | None]:
        """Return a terminal import projection from persisted runtime facts."""

        if receipt.runtime_job_id is None or receipt.runtime_session_id is None:
            return None, None
        reader = self._runtime_reader
        if reader is None:
            from writing_runtime import get_writing_runtime

            reader = get_writing_runtime()
            self._runtime_reader = reader
        job = reader.get_job(receipt.runtime_job_id)
        if job is None:
            return None, None
        job_id = str(getattr(job, "job_id", "") or "").strip()
        session_id = str(getattr(job, "session_id", "") or "").strip()
        if job_id != receipt.runtime_job_id or session_id != receipt.runtime_session_id:
            raise AcquisitionConflictError(
                "runtime_import_identity_mismatch",
                "Runtime job identity does not match the import receipt",
            )
        job_status = _runtime_status(getattr(job, "status", None))
        try:
            task = reader.get_material_processing_task(receipt.runtime_job_id)
        except ValueError as exc:
            raise AcquisitionConflictError(
                "runtime_import_state_invalid",
                "Runtime material-processing state could not be read",
            ) from exc
        task_status = _runtime_task_status(task, receipt)

        failure_statuses = {"failed", "cancelled", "approval_rejected"}
        if job_status in failure_statuses or task_status in {"failed", "cancelled"}:
            return ImportStatus.FAILED, _runtime_failure_message(job, task, job_status, task_status)
        if job_status == "completed" or task_status == "completed":
            return ImportStatus.COMPLETED, None
        return None, None

    def recover_interrupted_jobs(self) -> tuple[DownloadJob, ...]:
        """Requeue interrupted transfers without launching network work."""

        return self.store.recover_interrupted_jobs()

    async def _search_source(
        self,
        adapter: SourceAdapter,
        query: SearchQuery,
        *,
        run_id: str,
    ) -> tuple[CandidateManifest, ...]:
        """Serialize one source and enforce its minimum request-start interval."""

        source_id = adapter.policy.source_id
        lock = self._source_search_locks.get(source_id)
        if lock is None:
            lock = asyncio.Lock()
            self._source_search_locks[source_id] = lock
        async with lock:
            now = self._monotonic()
            previous = self._source_last_started.get(source_id)
            if previous is not None:
                delay = max(0.0, adapter.policy.min_interval_seconds - (now - previous))
                if delay > 0:
                    await self._sleep(delay)
            self._source_last_started[source_id] = self._monotonic()
            return await adapter.search(query, run_id=run_id)

    def _append_search_attempt(
        self,
        *,
        run: SearchRun,
        source_id: str,
        ordinal: int,
        outcome: AcquisitionAttemptOutcome,
        started_at: datetime,
        result_count: int | None = None,
        error_class: str | None = None,
        error_message: str | None = None,
        gate_id: str | None = None,
        retryable: bool = False,
        next_action: str | None = None,
    ) -> AcquisitionAttempt:
        """Append one bounded source-search audit record."""

        finished_at = utc_now()
        elapsed_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
        attempt_id = f"attempt_{_stable_digest(run.run_id, source_id, 'search', str(ordinal))[:24]}"
        return self.store.append_acquisition_attempt(
            AcquisitionAttempt(
                attempt_id=attempt_id,
                project_id=run.query.project_id,
                run_id=run.run_id,
                source_id=source_id,
                stage=AcquisitionAttemptStage.SEARCH,
                outcome=outcome,
                ordinal=ordinal,
                result_count=result_count,
                error_class=error_class,
                error_message=error_message,
                elapsed_ms=elapsed_ms,
                gate_id=gate_id,
                retryable=retryable,
                next_action=next_action,
                started_at=started_at,
                finished_at=finished_at,
            )
        )

    def _append_download_attempt(
        self,
        job: DownloadJob,
        *,
        outcome: AcquisitionAttemptOutcome,
        started_at: datetime,
        error_class: str | None = None,
        error_message: str | None = None,
        gate_id: str | None = None,
        retryable: bool = False,
        next_action: str | None = None,
    ) -> AcquisitionAttempt:
        """Append one terminal audit record for a download invocation."""

        return self.store.append_acquisition_attempt(
            self._build_download_attempt(
                job,
                outcome=outcome,
                started_at=started_at,
                error_class=error_class,
                error_message=error_message,
                gate_id=gate_id,
                retryable=retryable,
                next_action=next_action,
            )
        )

    @staticmethod
    def _build_download_attempt(
        job: DownloadJob,
        *,
        outcome: AcquisitionAttemptOutcome,
        started_at: datetime,
        error_class: str | None = None,
        error_message: str | None = None,
        gate_id: str | None = None,
        retryable: bool = False,
        next_action: str | None = None,
    ) -> AcquisitionAttempt:
        """Build the current invocation audit record before atomic settlement."""

        finished_at = utc_now()
        elapsed_ms = min(
            86_400_000,
            max(0, int((finished_at - started_at).total_seconds() * 1000)),
        )
        return AcquisitionAttempt(
            attempt_id=_download_attempt_id(job),
            project_id=job.project_id,
            job_id=job.job_id,
            source_id=job.source_platform,
            stage=AcquisitionAttemptStage.DOWNLOAD,
            outcome=outcome,
            ordinal=job.attempts,
            error_class=error_class,
            error_message=error_message,
            elapsed_ms=elapsed_ms,
            gate_id=gate_id,
            retryable=retryable,
            next_action=next_action,
            started_at=started_at,
            finished_at=finished_at,
        )

    @staticmethod
    def _merge_candidate(
        candidates: list[CandidateManifest],
        incoming: CandidateManifest,
        receipts: list[IdentityMergeReceipt],
        *,
        retain_new: bool = True,
    ) -> None:
        """Merge a matching candidate or retain a bounded distinct candidate."""

        distinct_decisions: list[tuple[CandidateManifest, IdentityMatchMethod]] = []
        for index, current in enumerate(candidates):
            if current.candidate_id == incoming.candidate_id:
                if current != incoming:
                    raise AcquisitionConflictError(
                        "candidate_id_conflict",
                        "A source reused one candidate id for different metadata",
                    )
                return
            method = candidate_identity_match(current, incoming)
            outcome = (
                IdentityDecisionOutcome.DISTINCT
                if method is IdentityMatchMethod.DISTINCT
                else IdentityDecisionOutcome.MATCH
            )
            if outcome is IdentityDecisionOutcome.DISTINCT:
                distinct_decisions.append((current, method))
                continue
            merge_id = (
                "identity_"
                + _stable_digest(
                    incoming.run_id,
                    current.candidate_id,
                    incoming.candidate_id,
                    str(len(receipts)),
                )[:24]
            )
            receipts.append(
                IdentityMergeReceipt(
                    merge_id=merge_id,
                    run_id=incoming.run_id,
                    project_id=incoming.project_id,
                    canonical_candidate_id=current.candidate_id,
                    compared_candidate_id=incoming.candidate_id,
                    outcome=outcome,
                    method=method,
                    merged=outcome is IdentityDecisionOutcome.MATCH,
                    evidence=candidate_identity_evidence(current, incoming, method),
                )
            )
            merged, _ = merge_candidate_manifests(current, incoming)
            candidates[index] = merged
            return
        if not retain_new:
            return
        for current, method in distinct_decisions:
            merge_id = (
                "identity_"
                + _stable_digest(
                    incoming.run_id,
                    current.candidate_id,
                    incoming.candidate_id,
                    str(len(receipts)),
                )[:24]
            )
            receipts.append(
                IdentityMergeReceipt(
                    merge_id=merge_id,
                    run_id=incoming.run_id,
                    project_id=incoming.project_id,
                    canonical_candidate_id=current.candidate_id,
                    compared_candidate_id=incoming.candidate_id,
                    outcome=IdentityDecisionOutcome.DISTINCT,
                    method=method,
                    merged=False,
                    evidence=candidate_identity_evidence(current, incoming, method),
                )
            )
        candidates.append(incoming)

    @staticmethod
    def _build_candidate_version_relations(
        candidates: Sequence[CandidateManifest],
        *,
        created_at: datetime,
    ) -> tuple[CandidateVersionRelation, ...]:
        relations: dict[str, CandidateVersionRelation] = {}
        for left_index, left in enumerate(candidates):
            for right in candidates[left_index + 1 :]:
                relation = build_explicit_version_relation(left, right, created_at=created_at)
                if relation is not None:
                    relations.setdefault(relation.relation_id, relation)
        return tuple(relations.values())

    def _persist_search_gate(
        self,
        *,
        run_id: str,
        query: SearchQuery,
        source_id: str,
        gate_type: str,
        url: str,
        message: str,
    ) -> HumanAccessGate:
        gate_id = f"gate_{_stable_digest(run_id, source_id, gate_type, url)[:24]}"
        gate = HumanAccessGate(
            gate_id=gate_id,
            project_id=query.project_id,
            platform=source_id,
            gate_type=gate_type,
            url=url,
            message=message,
            next_action="Complete the access step in a visible browser before a new explicit search.",
        )
        return self.store.save_gate(gate)

    def _authorize_candidate_download(
        self,
        *,
        project_id: str,
        candidate_id: str,
        access_evidence_id: str,
    ) -> tuple[CandidateManifest, PdfCandidate, SourcePolicy]:
        candidate = self.store.get_candidate(candidate_id)
        if candidate is None:
            raise AcquisitionNotFoundError("candidate_not_found", f"Candidate not found: {candidate_id}")
        if candidate.project_id != project_id:
            raise AcquisitionPolicyError("candidate_project_mismatch", "Candidate belongs to another project")
        pdf = next(
            (
                item
                for item in candidate.pdf_candidates
                if item.access_evidence.evidence_id == access_evidence_id
            ),
            None,
        )
        if pdf is None:
            raise AcquisitionPolicyError(
                "access_evidence_not_found",
                "Exact access evidence is required before download",
            )
        try:
            policy = self.registry.get(pdf.source_platform).policy
        except KeyError as exc:
            raise AcquisitionPolicyError("source_unavailable", "Source policy is unavailable") from exc
        evidence = pdf.access_evidence
        if evidence.access_route is not AccessRoute.OPEN_ACCESS:
            raise AcquisitionPolicyError("not_open_access", "Automatic download requires open-access evidence")
        if evidence.kind not in policy.evidence_kinds:
            raise AcquisitionPolicyError("evidence_not_allowed", "Source policy does not accept this evidence kind")
        if evidence.pdf_url != pdf.pdf_url or evidence.source_platform != policy.source_id:
            raise AcquisitionPolicyError("evidence_route_mismatch", "Access evidence does not match the PDF route")
        if "download" not in policy.capabilities or policy.requires_authentication or not policy.enabled:
            raise AcquisitionPolicyError("download_not_allowed", "Source policy does not allow automatic download")
        return candidate, pdf, policy

    @staticmethod
    def _validate_promotion_proof(
        proof: ArtifactPromotionProof,
        job: DownloadJob,
        access_evidence: AccessEvidence,
        validation: PdfValidationResult,
    ) -> None:
        """Require exact durable bindings before trusting promoted PDF bytes."""

        expected_artifact_id = f"artifact_{_stable_digest(job.job_id, validation.sha256)[:24]}"
        if (
            proof.artifact_id != expected_artifact_id
            or proof.job_id != job.job_id
            or proof.project_id != job.project_id
            or proof.candidate_id != job.candidate_id
            or proof.source_platform != job.source_platform
            or proof.source_url != job.source_url
            or proof.relative_path != job.artifact_path
            or proof.access_evidence != access_evidence
            or proof.size_bytes != validation.size_bytes
            or proof.sha256 != validation.sha256
            or proof.page_count != validation.page_count
            or proof.validation.validator_id != PDF_VALIDATOR_ID
            or proof.validation.validator_version != PDF_VALIDATOR_VERSION
            or proof.validation.parser_id != PDF_PARSER_ID
            or proof.validation.parser_version != PDF_PARSER_VERSION
            or proof.validation.checks != PDF_VALIDATION_CHECKS
        ):
            raise DownloadTransferError(
                "artifact_proof_mismatch",
                "Existing PDF does not match its durable promotion proof",
                bytes_downloaded=validation.size_bytes,
            )

    def _transition_download_to_cancelled(self, job_id: str) -> DownloadJob:
        """CAS-transition a job to cancelled while tolerating worker races."""

        current = self._require_download_job(job_id)
        for _attempt in range(8):
            if current.status is DownloadJobStatus.CANCELLED:
                return current
            if current.status is DownloadJobStatus.COMPLETED:
                raise AcquisitionConflictError(
                    "download_completed",
                    "Completed downloads cannot be cancelled",
                )
            try:
                if current.status in {
                    DownloadJobStatus.RUNNING,
                    DownloadJobStatus.VALIDATING,
                }:
                    attempt = self._build_download_attempt(
                        current,
                        outcome=AcquisitionAttemptOutcome.CANCELLED,
                        started_at=current.started_at or current.updated_at,
                    )
                    settled, _, _ = self.store.settle_download_job(
                        current.job_id,
                        expected_version=current.version,
                        from_statuses=(current.status,),
                        to_status=DownloadJobStatus.CANCELLED,
                        attempt=attempt,
                        bytes_downloaded=current.bytes_downloaded,
                    )
                    return settled
                return self.store.transition_download_job(
                    current.job_id,
                    expected_version=current.version,
                    from_statuses=(current.status,),
                    to_status=DownloadJobStatus.CANCELLED,
                    bytes_downloaded=current.bytes_downloaded,
                )
            except AcquisitionStoreConflictError:
                current = self._require_download_job(current.job_id)
        raise AcquisitionConflictError(
            "download_control_conflict",
            "Download state changed repeatedly while cancelling",
        )

    def _cleanup_cancelled_download(self, cancelled: DownloadJob) -> DownloadJob:
        """Converge cancelled files, proof, and durable cleanup status."""

        current = cancelled
        for _attempt in range(8):
            if current.status is not DownloadJobStatus.CANCELLED:
                if current.status is DownloadJobStatus.COMPLETED:
                    raise AcquisitionConflictError(
                        "download_completed",
                        "Download completed before cancellation cleanup finished",
                    )
                raise AcquisitionConflictError(
                    "download_control_conflict",
                    "Download state changed before cancellation cleanup",
                )
            try:
                self._remove_cancelled_download_files(current)
            except AcquisitionConflictError as exc:
                try:
                    self.store.record_cancelled_download_cleanup_failure(
                        current.job_id,
                        expected_version=current.version,
                        error_message=exc.safe_message,
                    )
                except AcquisitionStoreConflictError:
                    latest = self._require_download_job(current.job_id)
                    if latest.status is DownloadJobStatus.CANCELLED:
                        current = latest
                        continue
                    raise AcquisitionConflictError(
                        "download_control_conflict",
                        "Download state changed while recording cancellation cleanup failure",
                    ) from exc
                except AcquisitionStoreError as persist_exc:
                    raise AcquisitionConflictError(
                        "cancel_cleanup_failed",
                        "Cancellation cleanup failure could not be persisted",
                    ) from persist_exc
                raise AcquisitionConflictError(
                    "cancel_cleanup_failed",
                    exc.safe_message,
                ) from exc
            try:
                return self.store.finalize_cancelled_download_cleanup(
                    current.job_id,
                    expected_version=current.version,
                )
            except AcquisitionStoreConflictError:
                latest = self._require_download_job(current.job_id)
                if latest.status is DownloadJobStatus.CANCELLED:
                    current = latest
                    continue
                if latest.status is DownloadJobStatus.COMPLETED:
                    raise AcquisitionConflictError(
                        "download_completed",
                        "Download completed before cancellation cleanup finished",
                    )
                raise AcquisitionConflictError(
                    "download_control_conflict",
                    "Download state changed before cancellation cleanup finalized",
                )
            except AcquisitionStoreError as exc:
                message = "Cancellation cleanup could not be committed"
                try:
                    self.store.record_cancelled_download_cleanup_failure(
                        current.job_id,
                        expected_version=current.version,
                        error_message=message,
                    )
                except AcquisitionStoreConflictError:
                    latest = self._require_download_job(current.job_id)
                    if latest.status is DownloadJobStatus.CANCELLED:
                        current = latest
                        continue
                    raise AcquisitionConflictError(
                        "download_control_conflict",
                        "Download state changed while finalizing cancellation cleanup",
                    ) from exc
                except AcquisitionStoreError as persist_exc:
                    raise AcquisitionConflictError(
                        "cancel_cleanup_failed",
                        "Cancellation cleanup failure could not be persisted",
                    ) from persist_exc
                raise AcquisitionConflictError("cancel_cleanup_failed", message) from exc
        raise AcquisitionConflictError(
            "download_control_conflict",
            "Download state changed repeatedly during cancellation cleanup",
        )

    def _remove_cancelled_download_files(self, job: DownloadJob) -> None:
        """Remove final and adjacent partial files without following links."""

        try:
            project_root = self._project_path(job.project_id).resolve()
            candidate = project_root.joinpath(*Path(job.artifact_path).parts)
            for parent in candidate.parents:
                if parent == project_root:
                    break
                if parent.is_symlink():
                    raise DownloadPolicyError(
                        "download output path contains a symbolic link"
                    )
            if candidate.is_symlink():
                raise DownloadPolicyError(
                    "download output path is a symbolic link"
                )
            validate_download_destination(candidate, project_root)
        except Exception as exc:
            raise AcquisitionConflictError(
                "cancel_cleanup_failed",
                "Download output path is unsafe or not a regular PDF",
            ) from exc
        part = candidate.with_name(f"{candidate.name}.part")
        for path, description in ((part, "partial"), (candidate, "final")):
            try:
                if path.is_symlink():
                    raise AcquisitionConflictError(
                        "cancel_cleanup_failed",
                        f"Download {description} path is a symbolic link",
                    )
                if path.exists() and not path.is_file():
                    raise AcquisitionConflictError(
                        "cancel_cleanup_failed",
                        f"Download {description} path is not a regular file",
                    )
                path.unlink(missing_ok=True)
            except AcquisitionConflictError:
                raise
            except OSError as exc:
                raise AcquisitionConflictError(
                    "cancel_cleanup_failed",
                    f"Download {description} file could not be removed",
                ) from exc

    def _require_download_job(self, job_id: str) -> DownloadJob:
        job = self.store.get_download_job(job_id)
        if job is None:
            raise AcquisitionNotFoundError("download_not_found", f"Download not found: {job_id}")
        return job

    def _settle_control_state(
        self,
        running: DownloadJob,
        status: DownloadJobStatus,
        bytes_downloaded: int,
        *,
        attempt: AcquisitionAttempt,
    ) -> DownloadJob:
        latest = self._require_download_job(running.job_id)
        if latest.status is status:
            return latest
        if latest.status is not DownloadJobStatus.RUNNING:
            raise AcquisitionConflictError("download_control_conflict", "Download control state changed")
        settled, _, _ = self.store.settle_download_job(
            latest.job_id,
            expected_version=latest.version,
            from_statuses=(DownloadJobStatus.RUNNING,),
            to_status=status,
            attempt=attempt,
            bytes_downloaded=bytes_downloaded,
        )
        return settled

    def _open_download_gate(
        self,
        running: DownloadJob,
        exc: DownloadHumanGateRequired,
        *,
        started_at: datetime,
    ) -> DownloadJob:
        gate_id = f"gate_{_stable_digest(running.job_id, str(running.attempts), exc.gate_type, exc.url)[:24]}"
        gate = HumanAccessGate(
            gate_id=gate_id,
            project_id=running.project_id,
            job_id=running.job_id,
            platform=running.source_platform,
            gate_type=exc.gate_type,
            url=exc.url,
            message=exc.safe_message,
            next_action="Complete the access step in a visible browser, then explicitly resolve this gate.",
        )
        attempt = self._build_download_attempt(
            running,
            outcome=AcquisitionAttemptOutcome.HUMAN_REQUIRED,
            started_at=started_at,
            error_class=exc.code,
            error_message=exc.safe_message,
            gate_id=gate.gate_id,
            next_action=gate.next_action,
        )
        settled, _, _ = self.store.settle_download_job(
            running.job_id,
            expected_version=running.version,
            from_statuses=(DownloadJobStatus.RUNNING,),
            to_status=DownloadJobStatus.HUMAN_REQUIRED,
            attempt=attempt,
            bytes_downloaded=exc.bytes_downloaded,
            error_code=exc.code,
            error_message=exc.safe_message,
            gate=gate,
        )
        return settled

    def _fail_running_download(
        self,
        running: DownloadJob,
        code: str,
        message: str,
        bytes_downloaded: int,
        *,
        attempt: AcquisitionAttempt,
    ) -> DownloadJob:
        latest = self._require_download_job(running.job_id)
        if latest.status not in {DownloadJobStatus.RUNNING, DownloadJobStatus.VALIDATING}:
            return latest
        settled, _, _ = self.store.settle_download_job(
            latest.job_id,
            expected_version=latest.version,
            from_statuses=(latest.status,),
            to_status=DownloadJobStatus.FAILED,
            attempt=attempt,
            bytes_downloaded=bytes_downloaded,
            error_code=code,
            error_message=message,
        )
        return settled


def _stable_digest(*parts: str) -> str:
    encoded = "\0".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _download_attempt_id(job: DownloadJob) -> str:
    """Return the stable audit id for the job's current invocation ordinal."""

    return f"attempt_{_stable_digest(job.job_id, 'download', str(job.attempts))[:24]}"


def _required_result_text(result: Mapping[str, object], key: str) -> str:
    value = str(result.get(key) or "").strip()
    if not value:
        raise AcquisitionConflictError("invalid_ingest_result", f"Ingest result omitted {key}")
    return value


def _optional_result_text(result: Mapping[str, object], key: str) -> str | None:
    value = str(result.get(key) or "").strip()
    return value or None


def build_default_acquisition_service() -> LiteratureAcquisitionService:
    """Build the process-local service without starting network work."""

    from project_paths import runtime_state_path

    store = AcquisitionStore(runtime_state_path("acquisition", "acquisition.sqlite3"))
    service = LiteratureAcquisitionService(store)
    service.recover_interrupted_jobs()
    service.reconcile_import_receipts()
    return service


def _runtime_status(value: object) -> str:
    """Normalize an enum or string runtime lifecycle value."""

    normalized = str(getattr(value, "value", value) or "").strip().lower()
    allowed = {
        "created",
        "queued",
        "started",
        "paused",
        "in_progress",
        "approval_pending",
        "approval_rejected",
        "completed",
        "failed",
        "cancelled",
    }
    if normalized not in allowed:
        raise AcquisitionConflictError(
            "runtime_import_state_invalid",
            "Runtime job has an unsupported lifecycle state",
        )
    return normalized


def _runtime_task_status(
    task: Mapping[str, object] | None,
    receipt: ImportReceipt,
) -> str | None:
    """Validate and normalize an optional material-processing task state."""

    if task is None:
        return None
    task_job_id = str(task.get("job_id") or "").strip()
    task_session_id = str(task.get("session_id") or "").strip()
    if task_job_id and task_job_id != receipt.runtime_job_id:
        raise AcquisitionConflictError(
            "runtime_import_identity_mismatch",
            "Runtime material task does not match the import receipt job",
        )
    if task_session_id and task_session_id != receipt.runtime_session_id:
        raise AcquisitionConflictError(
            "runtime_import_identity_mismatch",
            "Runtime material task does not match the import receipt session",
        )
    normalized = str(task.get("status") or "").strip().lower()
    allowed = {
        "created",
        "queued",
        "started",
        "running",
        "in_progress",
        "paused",
        "completed",
        "failed",
        "cancelled",
    }
    if normalized not in allowed:
        raise AcquisitionConflictError(
            "runtime_import_state_invalid",
            "Runtime material task has an unsupported lifecycle state",
        )
    return normalized


def _runtime_failure_message(
    job: RuntimeJobRecord,
    task: Mapping[str, object] | None,
    job_status: str,
    task_status: str | None,
) -> str:
    """Return bounded user-safe failure text without exposing raw payloads."""

    candidates: list[object] = [getattr(job, "error", None)]
    if task is not None:
        result = task.get("result")
        if isinstance(result, Mapping):
            candidates.append(result.get("error"))
        warnings = task.get("warnings")
        if isinstance(warnings, Sequence) and not isinstance(warnings, (str, bytes)) and warnings:
            candidates.append(warnings[0])
    for candidate in candidates:
        normalized = " ".join(str(candidate or "").split())[:500]
        if normalized:
            return normalized
    terminal = task_status if task_status in {"failed", "cancelled"} else job_status
    return f"Runtime material ingestion ended with status: {terminal}"[:500]
