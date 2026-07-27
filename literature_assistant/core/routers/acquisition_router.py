"""Typed HTTP adapter for explicit, compliant literature acquisition."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from literature_assistant.core.acquisition.models import (
        CandidateVersionRelation,
        DownloadJob,
        DownloadJobStatus,
        GateStatus,
        HumanAccessGate,
        IdentityMergeReceipt,
        ImportReceipt,
        SearchQuery,
        SearchRun,
        SourcePolicy,
        ValidatedArtifact,
    )
    from literature_assistant.core.acquisition.service import (
        AcquisitionConflictError,
        AcquisitionNotFoundError,
        AcquisitionPolicyError,
        AcquisitionServiceError,
        LiteratureAcquisitionService,
        build_default_acquisition_service,
    )
    from literature_assistant.core.acquisition.store import AcquisitionStoreError
    from literature_assistant.core.acquisition.validator import DEFAULT_MAX_PDF_BYTES
else:
    from acquisition.models import (
        CandidateVersionRelation,
        DownloadJob,
        DownloadJobStatus,
        GateStatus,
        HumanAccessGate,
        IdentityMergeReceipt,
        ImportReceipt,
        SearchQuery,
        SearchRun,
        SourcePolicy,
        ValidatedArtifact,
    )
    from acquisition.service import (
        AcquisitionConflictError,
        AcquisitionNotFoundError,
        AcquisitionPolicyError,
        AcquisitionServiceError,
        LiteratureAcquisitionService,
        build_default_acquisition_service,
    )
    from acquisition.store import AcquisitionStoreError
    from acquisition.validator import DEFAULT_MAX_PDF_BYTES


router = APIRouter(prefix="/api/acquisition", tags=["Literature Acquisition"])


class StrictRequest(BaseModel):
    """Reject unknown fields at the external acquisition boundary."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class QueueDownloadRequest(StrictRequest):
    """Exact OA evidence required to create one resumable download job."""

    project_id: str = Field(min_length=1, max_length=256)
    candidate_id: str = Field(min_length=1, max_length=256)
    access_evidence_id: str = Field(min_length=1, max_length=256)
    max_bytes: int = Field(default=DEFAULT_MAX_PDF_BYTES, ge=4096, le=DEFAULT_MAX_PDF_BYTES)


class DownloadControlRequest(StrictRequest):
    """Explicit local lifecycle transition for one download job."""

    action: Literal["pause", "resume", "cancel"]


class GateResolutionResponse(BaseModel):
    """Resolved user gate and the requeued download when one is attached."""

    model_config = ConfigDict(extra="forbid")

    gate: HumanAccessGate
    download_job: DownloadJob | None = None


class AcquisitionStatusResponse(BaseModel):
    """Bounded read model for desktop and MCP acquisition controls."""

    model_config = ConfigDict(extra="forbid")

    sources: tuple[SourcePolicy, ...]
    download_jobs: tuple[DownloadJob, ...]
    gates: tuple[HumanAccessGate, ...]


class SearchRunIdentityLedgerResponse(BaseModel):
    """Bounded persisted identity decisions and explicit version edges."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    project_id: str
    identity_receipts: tuple[IdentityMergeReceipt, ...]
    version_relations: tuple[CandidateVersionRelation, ...]


@lru_cache(maxsize=1)
def get_acquisition_service() -> LiteratureAcquisitionService:
    """Return the process-local service shared by every HTTP caller."""

    return build_default_acquisition_service()


def _map_service_error(exc: Exception) -> HTTPException:
    """Convert bounded service/store failures into stable HTTP envelopes."""

    if isinstance(exc, AcquisitionNotFoundError):
        return HTTPException(status_code=404, detail={"code": exc.code, "message": exc.safe_message})
    if isinstance(exc, AcquisitionConflictError):
        return HTTPException(status_code=409, detail={"code": exc.code, "message": exc.safe_message})
    if isinstance(exc, AcquisitionPolicyError):
        return HTTPException(status_code=403, detail={"code": exc.code, "message": exc.safe_message})
    if isinstance(exc, AcquisitionServiceError):
        return HTTPException(status_code=400, detail={"code": exc.code, "message": exc.safe_message})
    return HTTPException(
        status_code=500,
        detail={"code": "acquisition_store_error", "message": "Acquisition state could not be read or updated"},
    )


@router.get("/status", response_model=AcquisitionStatusResponse)
def acquisition_status(
    project_id: str | None = Query(default=None, min_length=1, max_length=256),
    limit: int = Query(default=100, ge=1, le=500),
    service: LiteratureAcquisitionService = Depends(get_acquisition_service),
) -> AcquisitionStatusResponse:
    """Read enabled sources plus bounded jobs and user-owned gates."""

    try:
        return AcquisitionStatusResponse(
            sources=service.list_source_policies(),
            download_jobs=service.list_download_jobs(project_id=project_id, limit=limit),
            gates=service.list_gates(project_id=project_id, limit=limit),
        )
    except (AcquisitionServiceError, AcquisitionStoreError) as exc:
        raise _map_service_error(exc) from exc


@router.post("/search", response_model=SearchRun)
async def search_literature(
    request: SearchQuery,
    service: LiteratureAcquisitionService = Depends(get_acquisition_service),
) -> SearchRun:
    """Run one explicit allowlisted metadata search."""

    try:
        return await service.search(request)
    except (AcquisitionServiceError, AcquisitionStoreError) as exc:
        raise _map_service_error(exc) from exc


@router.get("/search-runs/{run_id}", response_model=SearchRun)
def get_search_run(
    run_id: str,
    service: LiteratureAcquisitionService = Depends(get_acquisition_service),
) -> SearchRun:
    """Read one durable search manifest without external work."""

    try:
        return service.get_search_run(run_id)
    except (AcquisitionServiceError, AcquisitionStoreError) as exc:
        raise _map_service_error(exc) from exc


@router.get(
    "/search-runs/{run_id}/identity-ledger",
    response_model=SearchRunIdentityLedgerResponse,
)
def get_search_run_identity_ledger(
    run_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    service: LiteratureAcquisitionService = Depends(get_acquisition_service),
) -> SearchRunIdentityLedgerResponse:
    """Read persisted search identity evidence without recomputing decisions."""

    try:
        run = service.get_search_run(run_id)
        return SearchRunIdentityLedgerResponse(
            run_id=run.run_id,
            project_id=run.query.project_id,
            identity_receipts=service.list_identity_merge_receipts(run_id, limit=limit),
            version_relations=service.list_candidate_version_relations(run_id, limit=limit),
        )
    except (AcquisitionServiceError, AcquisitionStoreError) as exc:
        raise _map_service_error(exc) from exc


@router.post("/downloads", response_model=DownloadJob)
def queue_download(
    request: QueueDownloadRequest,
    service: LiteratureAcquisitionService = Depends(get_acquisition_service),
) -> DownloadJob:
    """Queue one PDF only from exact allowlisted open-access evidence."""

    try:
        return service.queue_download(**request.model_dump())
    except (AcquisitionServiceError, AcquisitionStoreError) as exc:
        raise _map_service_error(exc) from exc


@router.get("/downloads/{job_id}", response_model=DownloadJob)
def get_download_job(
    job_id: str,
    service: LiteratureAcquisitionService = Depends(get_acquisition_service),
) -> DownloadJob:
    """Read one durable download job without starting network work."""

    try:
        return service.get_download_job(job_id)
    except (AcquisitionServiceError, AcquisitionStoreError) as exc:
        raise _map_service_error(exc) from exc


@router.post("/downloads/{job_id}/run", response_model=DownloadJob)
async def run_download(
    job_id: str,
    service: LiteratureAcquisitionService = Depends(get_acquisition_service),
) -> DownloadJob:
    """Explicitly run or retry one queued download job."""

    try:
        return await service.run_download(job_id)
    except (AcquisitionServiceError, AcquisitionStoreError) as exc:
        raise _map_service_error(exc) from exc


@router.post("/downloads/{job_id}/control", response_model=DownloadJob)
def control_download(
    job_id: str,
    request: DownloadControlRequest,
    service: LiteratureAcquisitionService = Depends(get_acquisition_service),
) -> DownloadJob:
    """Pause, resume, or cancel one job without hidden external work."""

    try:
        if request.action == "pause":
            return service.pause_download(job_id)
        if request.action == "resume":
            return service.resume_download(job_id)
        return service.cancel_download(job_id)
    except (AcquisitionServiceError, AcquisitionStoreError) as exc:
        raise _map_service_error(exc) from exc


@router.post("/gates/{gate_id}/resolve", response_model=GateResolutionResponse)
def resolve_gate(
    gate_id: str,
    service: LiteratureAcquisitionService = Depends(get_acquisition_service),
) -> GateResolutionResponse:
    """Acknowledge a completed visible user access step and requeue its job."""

    try:
        gate, download_job = service.resolve_gate(gate_id)
        return GateResolutionResponse(gate=gate, download_job=download_job)
    except (AcquisitionServiceError, AcquisitionStoreError) as exc:
        raise _map_service_error(exc) from exc


@router.get("/gates/{gate_id}", response_model=HumanAccessGate)
def get_gate(
    gate_id: str,
    service: LiteratureAcquisitionService = Depends(get_acquisition_service),
) -> HumanAccessGate:
    """Read one durable human-access gate without resolving it."""

    try:
        return service.get_gate(gate_id)
    except (AcquisitionServiceError, AcquisitionStoreError) as exc:
        raise _map_service_error(exc) from exc


@router.get("/artifacts/{artifact_id}", response_model=ValidatedArtifact)
def get_artifact(
    artifact_id: str,
    service: LiteratureAcquisitionService = Depends(get_acquisition_service),
) -> ValidatedArtifact:
    """Read one validated PDF artifact without importing it."""

    try:
        return service.get_artifact(artifact_id)
    except (AcquisitionServiceError, AcquisitionStoreError) as exc:
        raise _map_service_error(exc) from exc


@router.post("/artifacts/{artifact_id}/import", response_model=ImportReceipt)
async def import_artifact(
    artifact_id: str,
    service: LiteratureAcquisitionService = Depends(get_acquisition_service),
) -> ImportReceipt:
    """Revalidate and import one PDF through the existing material pipeline."""

    try:
        return await service.import_artifact(artifact_id)
    except (AcquisitionServiceError, AcquisitionStoreError) as exc:
        raise _map_service_error(exc) from exc


@router.get("/receipts/{receipt_id}", response_model=ImportReceipt)
def get_import_receipt(
    receipt_id: str,
    service: LiteratureAcquisitionService = Depends(get_acquisition_service),
) -> ImportReceipt:
    """Read one durable import receipt without repeating ingestion."""

    try:
        return service.get_import_receipt(receipt_id)
    except (AcquisitionServiceError, AcquisitionStoreError) as exc:
        raise _map_service_error(exc) from exc
