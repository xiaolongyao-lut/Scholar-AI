from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
from pypdf import PdfWriter

from harness_protocols import JobKind, SessionMode
from acquisition.downloader import (
    DownloadPolicyError,
    DownloadTransferError,
    download_validated_pdf,
    validate_download_url,
)
from acquisition.models import (
    AcquisitionAttempt,
    AcquisitionAttemptOutcome,
    AcquisitionAttemptStage,
    AccessEvidence,
    AccessEvidenceKind,
    AccessRoute,
    ArtifactPromotionProof,
    CandidateManifest,
    CandidateSourceRecord,
    CandidateVersionRelation,
    DownloadJob,
    DownloadJobStatus,
    HumanAccessGate,
    IdentityDecisionOutcome,
    IdentityMatchMethod,
    ImportReceipt,
    ImportPublicationEvidence,
    ImportPublicationState,
    ImportStatus,
    PdfCandidate,
    PdfValidationProvenance,
    PublicationStage,
    SearchQuery,
    SearchRun,
    SearchRunStatus,
    SourcePolicy,
    ValidatedArtifact,
    VersionRelationEvidenceKind,
    VersionRelationType,
    candidate_identity_match,
    utc_now,
)
from acquisition.service import (
    AcquisitionConflictError,
    AcquisitionNotFoundError,
    AcquisitionPolicyError,
    LiteratureAcquisitionService,
)
from acquisition.sources.arxiv import ARXIV_POLICY, ArxivSourceAdapter
from acquisition.source_registry import SourceRegistry
from acquisition.store import AcquisitionStore, AcquisitionStoreConflictError
from acquisition.validator import (
    PDF_PARSER_ID,
    PDF_PARSER_VERSION,
    PDF_VALIDATION_CHECKS,
    PDF_VALIDATOR_ID,
    PDF_VALIDATOR_VERSION,
    PdfValidationResult,
    validate_pdf_file,
)
from routers import resources_router
from routers import acquisition_router
from writing_runtime import WritingRuntime


class _ForeignPublicationEvidence(BaseModel):
    """Pydantic evidence carrier with an intentionally unrelated class identity."""

    model_config = ConfigDict(extra="allow")


def _pdf_bytes() -> bytes:
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Subject": "fixture-" + ("x" * 6_000)})
    writer.write(buffer)
    payload = buffer.getvalue()
    assert len(payload) >= 4096
    return payload


def _publication_evidence(
    project_id: str,
    material_id: str,
    *,
    expected_source_fingerprint: str,
    expected_source_size: int,
) -> ImportPublicationEvidence:
    """Return strict publication proof for service-only fixture boundaries."""

    timestamp = utc_now()
    return ImportPublicationEvidence(
        project_id=project_id,
        material_id=material_id,
        source_fingerprint=expected_source_fingerprint,
        source_size_bytes=expected_source_size,
        document_content_sha256=f"sha256:{'1' * 64}",
        chunk_manifest_sha256=f"sha256:{'2' * 64}",
        chunk_hash_version="scholar-ai-chunk-hash/v1",
        material_chunk_file_sha256=f"sha256:{'3' * 64}",
        material_chunk_count=1,
        material_chunk_root_sha256=f"sha256:{'4' * 64}",
        chunk_store_version="5" * 64,
        fts_schema_version="scholar-ai-chunk-fts5-index/v1",
        fts_chunk_store_version="5" * 64,
        fts_indexed_count=1,
        fts_skipped_count=0,
        fts_material_indexed_count=1,
        revision_fingerprint=f"sha256:{'6' * 64}",
        revision_receipt_id="mrev-fixture",
        revision_applied_at=timestamp,
        verified_at=timestamp,
    )


def _call_publication_verifier_through_flat_router(
    monkeypatch: pytest.MonkeyPatch,
    evidence: object,
) -> object:
    from literature_assistant.core.acquisition.service import (
        _default_verify_material_publication,
    )

    expected_fingerprint = f"sha256:{'a' * 64}"

    def return_evidence(
        project_id: str,
        material_id: str,
        *,
        expected_source_fingerprint: str,
        expected_source_size: int,
    ) -> object:
        assert project_id == "project_fixture"
        assert material_id == "material_fixture"
        assert expected_source_fingerprint == expected_fingerprint
        assert expected_source_size == 4096
        return evidence

    monkeypatch.setattr(
        resources_router,
        "verify_material_publication",
        return_evidence,
    )
    return _default_verify_material_publication(
        "project_fixture",
        "material_fixture",
        expected_source_fingerprint=expected_fingerprint,
        expected_source_size=4096,
    )


def test_package_service_accepts_publication_evidence_from_flat_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the real flat-router import boundary compatible with package service."""

    from literature_assistant.core.acquisition.models import (
        ImportPublicationEvidence as CanonicalImportPublicationEvidence,
    )

    expected_fingerprint = f"sha256:{'a' * 64}"
    flat_evidence = _publication_evidence(
        "project_fixture",
        "material_fixture",
        expected_source_fingerprint=expected_fingerprint,
        expected_source_size=4096,
    )
    normalized = _call_publication_verifier_through_flat_router(
        monkeypatch,
        flat_evidence,
    )

    assert isinstance(normalized, CanonicalImportPublicationEvidence)
    assert normalized.model_dump(mode="json") == flat_evidence.model_dump(mode="json")


def test_package_service_normalizes_foreign_pydantic_publication_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revalidate a structurally valid Pydantic model with a foreign identity."""

    from literature_assistant.core.acquisition.models import (
        ImportPublicationEvidence as CanonicalImportPublicationEvidence,
    )

    expected_fingerprint = f"sha256:{'a' * 64}"
    expected = _publication_evidence(
        "project_fixture",
        "material_fixture",
        expected_source_fingerprint=expected_fingerprint,
        expected_source_size=4096,
    )
    foreign_evidence = _ForeignPublicationEvidence.model_validate(
        expected.model_dump(mode="python")
    )

    assert not isinstance(foreign_evidence, CanonicalImportPublicationEvidence)
    normalized = _call_publication_verifier_through_flat_router(
        monkeypatch,
        foreign_evidence,
    )

    assert isinstance(normalized, CanonicalImportPublicationEvidence)
    assert normalized.model_dump(mode="json") == expected.model_dump(mode="json")


@pytest.mark.parametrize(
    "invalid_evidence",
    (
        pytest.param(object(), id="non-pydantic-object"),
        pytest.param(
            _ForeignPublicationEvidence(project_id="project_fixture"),
            id="pydantic-model-missing-fields",
        ),
    ),
)
def test_package_service_rejects_invalid_publication_evidence(
    monkeypatch: pytest.MonkeyPatch,
    invalid_evidence: object,
) -> None:
    """Reject untyped and incomplete verifier results at the service boundary."""

    with pytest.raises(
        TypeError,
        match="material publication verifier returned invalid evidence",
    ):
        _call_publication_verifier_through_flat_router(monkeypatch, invalid_evidence)


def test_legacy_import_receipt_remains_explicitly_unverified() -> None:
    legacy_payload = {
        "receipt_id": "import_legacy_fixture",
        "artifact_id": "artifact_legacy_fixture",
        "project_id": "project_fixture",
        "candidate_id": "candidate_legacy_fixture",
        "material_id": "material_legacy_fixture",
        "status": "completed",
        "source_fingerprint": f"sha256:{'a' * 64}",
        "open_url": "/workbench/paper/material_legacy_fixture",
    }

    receipt = ImportReceipt.model_validate(legacy_payload)

    assert receipt.receipt_schema_version == "scholar-ai-import-receipt/v1"
    assert receipt.publication_state is ImportPublicationState.UNVERIFIED_LEGACY
    assert receipt.publication_evidence is None


def _candidate(*, authors: tuple[str, ...] = ("Alice Example",)) -> CandidateManifest:
    candidate_id = "cand_fixture"
    pdf_url = "https://arxiv.org/pdf/2401.00001.pdf"
    evidence = AccessEvidence(
        evidence_id="access_fixture",
        candidate_id=candidate_id,
        source_platform="arxiv",
        kind=AccessEvidenceKind.OFFICIAL_REPOSITORY,
        access_route=AccessRoute.OPEN_ACCESS,
        pdf_url=pdf_url,
        statement="Official repository PDF.",
    )
    return CandidateManifest(
        candidate_id=candidate_id,
        run_id="run_fixture",
        project_id="project_fixture",
        title="Shared title",
        authors=authors,
        year=2024,
        arxiv_id="2401.00001",
        source_platforms=("arxiv",),
        source_records=(
            CandidateSourceRecord(
                source_platform="arxiv",
                source_record_id="2401.00001",
                source_revision="v1",
                publication_stage=PublicationStage.PREPRINT,
            ),
        ),
        pdf_candidates=(
            PdfCandidate(
                pdf_url=pdf_url,
                source_platform="arxiv",
                access_evidence=evidence,
            ),
        ),
    )


def _store_candidate(store: AcquisitionStore, candidate: CandidateManifest) -> None:
    completed_at = utc_now()
    store.save_search_run(
        SearchRun(
            run_id=candidate.run_id,
            query=SearchQuery(
                project_id=candidate.project_id,
                query="fixture",
                sources=("arxiv",),
            ),
            status=SearchRunStatus.COMPLETED,
            requested_sources=("arxiv",),
            attempted_sources=("arxiv",),
            candidates=(candidate,),
            created_at=completed_at,
            completed_at=completed_at,
            updated_at=completed_at,
        )
    )


def test_acquisition_store_migrates_v1_identity_schema_without_losing_run(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "acquisition-v1.sqlite3"
    original = AcquisitionStore(db_path)
    candidate = _candidate()
    _store_candidate(original, candidate)

    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE candidate_version_relations")
        connection.execute("DROP TABLE identity_merge_receipts")
        connection.execute(
            "UPDATE acquisition_meta SET value = '1' WHERE key = 'schema_version'"
        )
        connection.commit()

    reopened = AcquisitionStore(db_path)
    assert reopened.get_candidate(candidate.candidate_id) == candidate
    assert reopened.list_identity_merge_receipts(candidate.run_id) == ()
    assert reopened.list_candidate_version_relations(candidate.run_id) == ()
    with sqlite3.connect(db_path) as connection:
        schema_version = connection.execute(
            "SELECT value FROM acquisition_meta WHERE key = 'schema_version'"
        ).fetchone()
    assert schema_version == ("3",)


def _job(*, status: DownloadJobStatus, gate_id: str | None = None) -> DownloadJob:
    return DownloadJob(
        job_id="download_fixture",
        project_id="project_fixture",
        candidate_id="cand_fixture",
        access_evidence_id="access_fixture",
        source_platform="arxiv",
        source_url="https://arxiv.org/pdf/2401.00001.pdf",
        artifact_path="source_files/acquired_fixture.pdf",
        status=status,
        gate_id=gate_id,
    )


def _download_attempt_id(job: DownloadJob) -> str:
    encoded = f"{job.job_id}\0download\0{job.attempts}".encode("utf-8")
    return f"attempt_{hashlib.sha256(encoded).hexdigest()[:24]}"


def _download_attempt(
    job: DownloadJob,
    outcome: AcquisitionAttemptOutcome,
    *,
    error_class: str | None = None,
    error_message: str | None = None,
    gate: HumanAccessGate | None = None,
    retryable: bool = False,
) -> AcquisitionAttempt:
    started_at = job.started_at or job.updated_at
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
        gate_id=None if gate is None else gate.gate_id,
        retryable=retryable,
        next_action=None if gate is None else gate.next_action,
        started_at=started_at,
        finished_at=utc_now(),
    )


def _running_job(store: AcquisitionStore) -> DownloadJob:
    queued = store.save_download_job(_job(status=DownloadJobStatus.QUEUED))
    return store.transition_download_job(
        queued.job_id,
        expected_version=queued.version,
        from_statuses=(DownloadJobStatus.QUEUED,),
        to_status=DownloadJobStatus.RUNNING,
    )


def _stable_artifact_id(job_id: str, sha256: str) -> str:
    digest = hashlib.sha256(f"{job_id}\0{sha256}".encode("utf-8")).hexdigest()
    return f"artifact_{digest[:24]}"


def _promotion_proof(
    job: DownloadJob,
    artifact: ValidatedArtifact,
    *,
    access_evidence: AccessEvidence | None = None,
) -> ArtifactPromotionProof:
    evidence = access_evidence or _candidate().pdf_candidates[0].access_evidence
    return ArtifactPromotionProof(
        proof_id=f"proof_{artifact.artifact_id}",
        artifact_id=artifact.artifact_id,
        job_id=job.job_id,
        attempt_id=f"attempt_{job.job_id}",
        project_id=job.project_id,
        candidate_id=job.candidate_id,
        source_platform=job.source_platform,
        source_url=job.source_url,
        final_url=job.source_url,
        access_evidence=evidence,
        relative_path=artifact.relative_path,
        size_bytes=artifact.size_bytes,
        sha256=artifact.sha256,
        page_count=artifact.page_count,
        validation=PdfValidationProvenance(
            validator_id=PDF_VALIDATOR_ID,
            validator_version=PDF_VALIDATOR_VERSION,
            parser_id=PDF_PARSER_ID,
            parser_version=PDF_PARSER_VERSION,
            checks=PDF_VALIDATION_CHECKS,
            validated_at=artifact.validated_at,
        ),
        prepared_at=artifact.validated_at,
    )


def _persist_validated_artifact(
    store: AcquisitionStore,
    *,
    job_id: str,
    relative_path: str,
    validation: PdfValidationResult,
) -> ValidatedArtifact:
    candidate = _candidate()
    if store.get_candidate(candidate.candidate_id) is None:
        _store_candidate(store, candidate)
    queued = store.save_download_job(
        DownloadJob(
            job_id=job_id,
            project_id=candidate.project_id,
            candidate_id=candidate.candidate_id,
            access_evidence_id=candidate.pdf_candidates[0].access_evidence.evidence_id,
            source_platform="arxiv",
            source_url=candidate.pdf_candidates[0].pdf_url,
            artifact_path=relative_path,
        )
    )
    running = store.transition_download_job(
        queued.job_id,
        expected_version=queued.version,
        from_statuses=(DownloadJobStatus.QUEUED,),
        to_status=DownloadJobStatus.RUNNING,
    )
    validating = store.transition_download_job(
        running.job_id,
        expected_version=running.version,
        from_statuses=(DownloadJobStatus.RUNNING,),
        to_status=DownloadJobStatus.VALIDATING,
    )
    artifact = ValidatedArtifact(
        artifact_id=_stable_artifact_id(validating.job_id, validation.sha256),
        job_id=validating.job_id,
        project_id=validating.project_id,
        candidate_id=validating.candidate_id,
        relative_path=validating.artifact_path,
        size_bytes=validation.size_bytes,
        sha256=validation.sha256,
        page_count=validation.page_count,
    )
    proof = store.save_artifact_promotion_proof(
        _promotion_proof(
            validating,
            artifact,
            access_evidence=candidate.pdf_candidates[0].access_evidence,
        )
    )
    store.complete_download_job(
        artifact,
        proof,
        expected_job_version=validating.version,
    )
    return artifact


def test_title_year_identity_requires_matching_full_author() -> None:
    left = _candidate(authors=("Alice Example",))
    unrelated = left.model_copy(
        update={"candidate_id": "cand_other", "authors": ("Bob Different",), "arxiv_id": None}
    )
    reordered = left.model_copy(
        update={"candidate_id": "cand_reordered", "authors": ("Example, Alice",), "arxiv_id": None}
    )
    left_without_identifier = left.model_copy(update={"arxiv_id": None})

    assert candidate_identity_match(left_without_identifier, unrelated) is IdentityMatchMethod.DISTINCT
    assert (
        candidate_identity_match(left_without_identifier, reordered)
        is IdentityMatchMethod.TITLE_YEAR
    )


@pytest.mark.asyncio
async def test_multi_source_search_merges_identity_and_persists_provenance(
    tmp_path: Path,
) -> None:
    second_policy = SourcePolicy(
        source_id="fixture_repository",
        capabilities=("search", "download"),
        metadata_hosts=("metadata.fixture.example",),
        download_hosts=("files.fixture.example",),
        evidence_kinds=(AccessEvidenceKind.OFFICIAL_REPOSITORY,),
        min_interval_seconds=0,
        terms_url="https://metadata.fixture.example/terms",
    )

    class _ArxivFixtureSource:
        policy = ARXIV_POLICY

        async def search(
            self,
            query: SearchQuery,
            *,
            run_id: str,
        ) -> tuple[CandidateManifest, ...]:
            return (
                _candidate().model_copy(
                    update={"run_id": run_id, "project_id": query.project_id}
                ),
            )

    class _RepositoryFixtureSource:
        policy = second_policy

        async def search(
            self,
            query: SearchQuery,
            *,
            run_id: str,
        ) -> tuple[CandidateManifest, ...]:
            candidate_id = "cand_fixture_repository"
            pdf_url = "https://files.fixture.example/paper.pdf"
            evidence = AccessEvidence(
                evidence_id="access_fixture_repository",
                candidate_id=candidate_id,
                source_platform=second_policy.source_id,
                kind=AccessEvidenceKind.OFFICIAL_REPOSITORY,
                access_route=AccessRoute.OPEN_ACCESS,
                pdf_url=pdf_url,
                statement="Fixture repository provides the open-access PDF.",
            )
            return (
                CandidateManifest(
                    candidate_id=candidate_id,
                    run_id=run_id,
                    project_id=query.project_id,
                    title="Shared title",
                    authors=("Example, Alice",),
                    year=2024,
                    arxiv_id="2401.00001",
                    source_platforms=(second_policy.source_id,),
                    pdf_candidates=(
                        PdfCandidate(
                            pdf_url=pdf_url,
                            source_platform=second_policy.source_id,
                            access_evidence=evidence,
                        ),
                    ),
                ),
            )

    store = AcquisitionStore(tmp_path / "acquisition.sqlite3")
    service = LiteratureAcquisitionService(
        store,
        registry=SourceRegistry((_ArxivFixtureSource(), _RepositoryFixtureSource())),
        project_path=lambda _project_id, *parts: tmp_path.joinpath(*parts),
        validate_project=lambda _project_id: None,
    )

    run = await service.search(
        SearchQuery(
            project_id="project_fixture",
            query="shared paper",
            sources=("arxiv", second_policy.source_id),
            max_results=5,
        )
    )

    assert run.status is SearchRunStatus.COMPLETED
    assert run.attempted_sources == ("arxiv", second_policy.source_id)
    assert len(run.candidates) == 1
    merged = run.candidates[0]
    assert merged.source_platforms == ("arxiv", second_policy.source_id)
    assert merged.merged_from_candidate_ids == ("cand_fixture_repository",)
    assert {item.source_platform for item in merged.pdf_candidates} == {
        "arxiv",
        second_policy.source_id,
    }
    assert store.get_search_run(run.run_id) == run
    receipts = service.list_identity_merge_receipts(run.run_id)
    assert len(receipts) == 1
    assert receipts[0].outcome is IdentityDecisionOutcome.MATCH
    assert receipts[0].method is IdentityMatchMethod.ARXIV_ID
    assert receipts[0].canonical_candidate_id == "cand_fixture"
    assert receipts[0].compared_candidate_id == "cand_fixture_repository"
    assert receipts[0].evidence == ("shared_arxiv_id:2401.00001",)


@pytest.mark.asyncio
async def test_arxiv_adapter_preserves_exact_source_revision() -> None:
    feed = b"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry>
        <id>https://arxiv.org/abs/2401.00001v3</id>
        <title>Versioned fixture</title>
        <summary>Fixture abstract.</summary>
        <published>2024-01-02T00:00:00Z</published>
        <author><name>Alice Example</name></author>
      </entry>
    </feed>"""

    def _response(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/atom+xml"}, content=feed)

    client = httpx.AsyncClient(transport=httpx.MockTransport(_response))
    try:
        candidates = await ArxivSourceAdapter(client).search(
            SearchQuery(
                project_id="project_fixture",
                query="versioned fixture",
                sources=("arxiv",),
            ),
            run_id="run_version_fixture",
        )
    finally:
        await client.aclose()

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.arxiv_id == "2401.00001"
    assert candidate.source_records == (
        CandidateSourceRecord(
            source_platform="arxiv",
            source_record_id="2401.00001",
            source_revision="v3",
            publication_stage=PublicationStage.PREPRINT,
        ),
    )
    assert candidate.landing_urls == ("https://arxiv.org/abs/2401.00001v3",)
    assert candidate.pdf_candidates[0].pdf_url == "https://arxiv.org/pdf/2401.00001v3.pdf"


@pytest.mark.asyncio
async def test_identity_and_version_ledgers_are_atomic_idempotent_and_reopenable(
    tmp_path: Path,
) -> None:
    revision_policy = SourcePolicy(
        source_id="revision_fixture",
        capabilities=("search",),
        metadata_hosts=("revision.fixture.example",),
        evidence_kinds=(AccessEvidenceKind.OFFICIAL_REPOSITORY,),
        min_interval_seconds=0,
        terms_url="https://revision.fixture.example/terms",
    )
    publication_policy = SourcePolicy(
        source_id="publication_fixture",
        capabilities=("search",),
        metadata_hosts=("publication.fixture.example",),
        evidence_kinds=(AccessEvidenceKind.OFFICIAL_REPOSITORY,),
        min_interval_seconds=0,
        terms_url="https://publication.fixture.example/terms",
    )

    def _manifest(
        *,
        candidate_id: str,
        run_id: str,
        project_id: str,
        source_platform: str,
        source_record_id: str,
        revision: str | None,
        stage: PublicationStage,
        title: str,
        doi: str | None = None,
        arxiv_id: str | None = None,
    ) -> CandidateManifest:
        return CandidateManifest(
            candidate_id=candidate_id,
            run_id=run_id,
            project_id=project_id,
            title=title,
            authors=("Alice Example",),
            year=2024,
            doi=doi,
            arxiv_id=arxiv_id,
            source_platforms=(source_platform,),
            source_records=(
                CandidateSourceRecord(
                    source_platform=source_platform,
                    source_record_id=source_record_id,
                    source_revision=revision,
                    publication_stage=stage,
                ),
            ),
        )

    class _RevisionSource:
        policy = revision_policy

        async def search(
            self,
            query: SearchQuery,
            *,
            run_id: str,
        ) -> tuple[CandidateManifest, ...]:
            common = {
                "run_id": run_id,
                "project_id": query.project_id,
                "source_platform": revision_policy.source_id,
                "source_record_id": "2401.00001",
                "stage": PublicationStage.PREPRINT,
                "title": "Revision fixture",
                "arxiv_id": "2401.00001",
            }
            return (
                _manifest(candidate_id="cand_revision_v1", revision="v1", **common),
                _manifest(candidate_id="cand_revision_v2", revision="v2", **common),
                _manifest(
                    candidate_id="cand_preprint",
                    run_id=run_id,
                    project_id=query.project_id,
                    source_platform=revision_policy.source_id,
                    source_record_id="2402.00002",
                    revision="v1",
                    stage=PublicationStage.PREPRINT,
                    title="Publication fixture",
                    doi="10.1000/publication-fixture",
                    arxiv_id="2402.00002",
                ),
            )

    class _PublicationSource:
        policy = publication_policy

        async def search(
            self,
            query: SearchQuery,
            *,
            run_id: str,
        ) -> tuple[CandidateManifest, ...]:
            return (
                _manifest(
                    candidate_id="cand_published",
                    run_id=run_id,
                    project_id=query.project_id,
                    source_platform=publication_policy.source_id,
                    source_record_id="10.1000/publication-fixture",
                    revision=None,
                    stage=PublicationStage.PUBLISHED,
                    title="Publication fixture",
                    doi="10.1000/publication-fixture",
                ),
                _manifest(
                    candidate_id="cand_title_only",
                    run_id=run_id,
                    project_id=query.project_id,
                    source_platform=publication_policy.source_id,
                    source_record_id="title-only",
                    revision=None,
                    stage=PublicationStage.UNKNOWN,
                    title="Publication fixture extended",
                ),
            )

    db_path = tmp_path / "identity-ledger.sqlite3"
    service = LiteratureAcquisitionService(
        AcquisitionStore(db_path),
        registry=SourceRegistry((_RevisionSource(), _PublicationSource())),
        validate_project=lambda _project_id: None,
    )
    run = await service.search(
        SearchQuery(
            project_id="project_fixture",
            query="identity versions",
            sources=(revision_policy.source_id, publication_policy.source_id),
            max_results=10,
        )
    )

    assert {candidate.candidate_id for candidate in run.candidates} == {
        "cand_revision_v1",
        "cand_revision_v2",
        "cand_preprint",
        "cand_published",
        "cand_title_only",
    }
    receipts = service.list_identity_merge_receipts(run.run_id, limit=100)
    relations = service.list_candidate_version_relations(run.run_id, limit=100)
    assert any(
        receipt.canonical_candidate_id == "cand_revision_v1"
        and receipt.compared_candidate_id == "cand_revision_v2"
        and receipt.outcome is IdentityDecisionOutcome.DISTINCT
        and receipt.evidence == (
            f"source_revision:{revision_policy.source_id}:2401.00001:v2->v1",
        )
        for receipt in receipts
    )
    assert {
        (
            relation.source_candidate_id,
            relation.target_candidate_id,
            relation.relation,
            relation.evidence_kind,
        )
        for relation in relations
    } == {
        (
            "cand_revision_v2",
            "cand_revision_v1",
            VersionRelationType.REVISION_OF,
            VersionRelationEvidenceKind.SOURCE_REVISION,
        ),
        (
            "cand_preprint",
            "cand_published",
            VersionRelationType.PREPRINT_OF,
            VersionRelationEvidenceKind.DOI_AND_SOURCE_STAGE,
        ),
    }
    assert all(
        "cand_title_only" not in {relation.source_candidate_id, relation.target_candidate_id}
        for relation in relations
    )

    reopened = AcquisitionStore(db_path)
    assert reopened.list_identity_merge_receipts(run.run_id, limit=100) == receipts
    assert reopened.list_candidate_version_relations(run.run_id, limit=100) == relations
    assert (
        reopened.save_search_run(
            run,
            identity_receipts=receipts,
            version_relations=relations,
        )
        == run
    )
    with pytest.raises(AcquisitionStoreConflictError):
        reopened.save_search_run(run)
    assert reopened.get_search_run(run.run_id) == run
    assert reopened.list_identity_merge_receipts(run.run_id, limit=100) == receipts
    assert reopened.list_candidate_version_relations(run.run_id, limit=100) == relations

    invalid_relation = CandidateVersionRelation(
        relation_id="version_missing_endpoint",
        run_id=run.run_id,
        project_id=run.query.project_id,
        source_candidate_id="cand_missing",
        target_candidate_id="cand_revision_v1",
        relation=VersionRelationType.REVISION_OF,
        evidence_kind=VersionRelationEvidenceKind.SOURCE_REVISION,
        evidence=("source_revision:fixture:missing:v2->v1",),
    )
    replacement = SearchRun.model_validate(
        run.model_copy(
            update={
                "version": run.version + 1,
                "updated_at": utc_now(),
            }
        ).model_dump(mode="python")
    )
    with pytest.raises(AcquisitionStoreConflictError):
        reopened.save_search_run(
            replacement,
            expected_version=run.version,
            identity_receipts=receipts,
            version_relations=(*relations, invalid_relation),
        )
    assert reopened.get_search_run(run.run_id) == run
    assert reopened.list_identity_merge_receipts(run.run_id, limit=100) == receipts
    assert reopened.list_candidate_version_relations(run.run_id, limit=100) == relations

    forged_relation = CandidateVersionRelation(
        relation_id="version_forged_title_edge",
        run_id=run.run_id,
        project_id=run.query.project_id,
        source_candidate_id="cand_title_only",
        target_candidate_id="cand_revision_v1",
        relation=VersionRelationType.REVISION_OF,
        evidence_kind=VersionRelationEvidenceKind.SOURCE_REVISION,
        evidence=("source_revision:fixture:forged:v2->v1",),
    )
    with pytest.raises(AcquisitionStoreConflictError):
        reopened.save_search_run(
            replacement,
            expected_version=run.version,
            identity_receipts=receipts,
            version_relations=(*relations, forged_relation),
        )
    assert reopened.get_search_run(run.run_id) == run
    assert reopened.list_identity_merge_receipts(run.run_id, limit=100) == receipts
    assert reopened.list_candidate_version_relations(run.run_id, limit=100) == relations


@pytest.mark.asyncio
async def test_source_policy_minimum_interval_is_enforced(tmp_path: Path) -> None:
    policy = SourcePolicy(
        source_id="rate_fixture",
        capabilities=("search",),
        metadata_hosts=("metadata.fixture.example",),
        evidence_kinds=(AccessEvidenceKind.OFFICIAL_REPOSITORY,),
        min_interval_seconds=2.5,
        terms_url="https://metadata.fixture.example/terms",
    )
    clock = [100.0]
    starts: list[float] = []
    delays: list[float] = []

    class _RateFixtureSource:
        @property
        def policy(self) -> SourcePolicy:
            return policy

        async def search(
            self,
            query: SearchQuery,
            *,
            run_id: str,
        ) -> tuple[CandidateManifest, ...]:
            del query, run_id
            starts.append(clock[0])
            return ()

    async def _sleep(delay: float) -> None:
        delays.append(delay)
        clock[0] += delay

    service = LiteratureAcquisitionService(
        AcquisitionStore(tmp_path / "rate.sqlite3"),
        registry=SourceRegistry((_RateFixtureSource(),)),
        validate_project=lambda _project_id: None,
        monotonic=lambda: clock[0],
        sleep=_sleep,
    )
    query = SearchQuery(
        project_id="project_fixture",
        query="rate limit",
        sources=(policy.source_id,),
    )

    await service.search(query)
    await service.search(query)

    assert starts == [100.0, 102.5]
    assert delays == [2.5]


@pytest.mark.asyncio
async def test_source_rate_limit_serializes_concurrent_searches(tmp_path: Path) -> None:
    policy = SourcePolicy(
        source_id="serial_fixture",
        capabilities=("search",),
        metadata_hosts=("metadata.fixture.example",),
        evidence_kinds=(AccessEvidenceKind.OFFICIAL_REPOSITORY,),
        min_interval_seconds=0,
        terms_url="https://metadata.fixture.example/terms",
    )
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    calls = 0
    active = 0
    max_active = 0

    class _SerialFixtureSource:
        @property
        def policy(self) -> SourcePolicy:
            return policy

        async def search(
            self,
            query: SearchQuery,
            *,
            run_id: str,
        ) -> tuple[CandidateManifest, ...]:
            del query, run_id
            nonlocal calls, active, max_active
            calls += 1
            active += 1
            max_active = max(max_active, active)
            if calls == 1:
                first_started.set()
                await release_first.wait()
            active -= 1
            return ()

    service = LiteratureAcquisitionService(
        AcquisitionStore(tmp_path / "serial.sqlite3"),
        registry=SourceRegistry((_SerialFixtureSource(),)),
        validate_project=lambda _project_id: None,
    )
    query = SearchQuery(
        project_id="project_fixture",
        query="serialize",
        sources=(policy.source_id,),
    )

    first = asyncio.create_task(service.search(query))
    await first_started.wait()
    second = asyncio.create_task(service.search(query))
    await asyncio.sleep(0)
    assert calls == 1
    release_first.set()
    await asyncio.gather(first, second)

    assert calls == 2
    assert max_active == 1


def test_download_requires_exact_access_evidence_and_allowlisted_host(tmp_path: Path) -> None:
    store = AcquisitionStore(tmp_path / "acquisition.sqlite3")
    candidate = _candidate()
    _store_candidate(store, candidate)
    service = LiteratureAcquisitionService(
        store,
        registry=SourceRegistry((ArxivSourceAdapter(),)),
        project_path=lambda _project_id, *parts: tmp_path.joinpath(*parts),
        validate_project=lambda _project_id: None,
    )

    with pytest.raises(AcquisitionPolicyError, match="Exact access evidence"):
        service.queue_download(
            project_id=candidate.project_id,
            candidate_id=candidate.candidate_id,
            access_evidence_id="access_missing",
        )
    with pytest.raises(DownloadPolicyError, match="not allowlisted"):
        validate_download_url(
            "https://example.com/paper.pdf",
            allowed_hosts=ARXIV_POLICY.download_hosts,
            resolver=lambda _host: ("93.184.216.34",),
        )


def test_store_completes_artifact_and_resolves_gate_atomically(tmp_path: Path) -> None:
    store = AcquisitionStore(tmp_path / "acquisition.sqlite3")
    gate = HumanAccessGate(
        gate_id="gate_fixture",
        project_id="project_fixture",
        job_id="download_fixture",
        platform="arxiv",
        gate_type="http_403",
        url="https://arxiv.org/pdf/2401.00001.pdf",
        message="Access stopped.",
        next_action="Resolve access explicitly.",
    )
    store.save_gate(gate)
    gated = store.save_download_job(_job(status=DownloadJobStatus.HUMAN_REQUIRED, gate_id=gate.gate_id))
    resolved, queued = store.resolve_gate_and_requeue_download(
        gate.gate_id,
        expected_gate_version=gate.version,
        expected_job_version=gated.version,
    )
    assert resolved.status.value == "resolved"
    assert queued.status is DownloadJobStatus.QUEUED
    assert queued.gate_id is None

    running = store.transition_download_job(
        queued.job_id,
        expected_version=queued.version,
        from_statuses=(DownloadJobStatus.QUEUED,),
        to_status=DownloadJobStatus.RUNNING,
    )
    validating = store.transition_download_job(
        running.job_id,
        expected_version=running.version,
        from_statuses=(DownloadJobStatus.RUNNING,),
        to_status=DownloadJobStatus.VALIDATING,
    )
    artifact = ValidatedArtifact(
        artifact_id="artifact_fixture",
        job_id=validating.job_id,
        project_id=validating.project_id,
        candidate_id=validating.candidate_id,
        relative_path=validating.artifact_path,
        size_bytes=4096,
        sha256="a" * 64,
        page_count=1,
    )
    proof = store.save_artifact_promotion_proof(_promotion_proof(validating, artifact))
    with pytest.raises(AcquisitionStoreConflictError):
        store.complete_download_job(
            artifact,
            proof,
            expected_job_version=validating.version + 1,
        )
    assert store.get_artifact(artifact.artifact_id) is None

    completed = store.complete_download_job(
        artifact,
        proof,
        expected_job_version=validating.version,
    )
    assert completed.status is DownloadJobStatus.COMPLETED
    assert completed.artifact_id == artifact.artifact_id
    assert store.get_artifact(artifact.artifact_id) == artifact


def test_terminal_job_and_attempt_roll_back_together_on_attempt_insert_failure(
    tmp_path: Path,
) -> None:
    store = AcquisitionStore(tmp_path / "acquisition.sqlite3")
    running = _running_job(store)
    attempt = _download_attempt(
        running,
        AcquisitionAttemptOutcome.FAILED,
        error_class="fixture_failure",
        error_message="Fixture terminal failure.",
    )
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "CREATE TRIGGER reject_fixture_attempt "
            "BEFORE INSERT ON acquisition_attempts "
            "BEGIN SELECT RAISE(ABORT, 'fixture attempt failure'); END"
        )

    with pytest.raises(AcquisitionStoreConflictError):
        store.settle_download_job(
            running.job_id,
            expected_version=running.version,
            from_statuses=(DownloadJobStatus.RUNNING,),
            to_status=DownloadJobStatus.FAILED,
            attempt=attempt,
            error_code=attempt.error_class,
            error_message=attempt.error_message,
        )

    assert store.get_download_job(running.job_id) == running
    assert store.list_acquisition_attempts(job_id=running.job_id) == ()


def test_terminal_settlement_cas_failure_has_no_partial_writes(tmp_path: Path) -> None:
    store = AcquisitionStore(tmp_path / "acquisition.sqlite3")
    running = _running_job(store)
    gate = HumanAccessGate(
        gate_id="gate_atomic_fixture",
        project_id=running.project_id,
        job_id=running.job_id,
        platform=running.source_platform,
        gate_type="http_403",
        url=running.source_url,
        message="Access requires user action.",
        next_action="Resolve access explicitly.",
    )
    attempt = _download_attempt(
        running,
        AcquisitionAttemptOutcome.HUMAN_REQUIRED,
        gate=gate,
    )

    with pytest.raises(AcquisitionStoreConflictError):
        store.settle_download_job(
            running.job_id,
            expected_version=running.version + 1,
            from_statuses=(DownloadJobStatus.RUNNING,),
            to_status=DownloadJobStatus.HUMAN_REQUIRED,
            attempt=attempt,
            gate=gate,
        )

    assert store.get_download_job(running.job_id) == running
    assert store.get_gate(gate.gate_id) is None
    assert store.list_acquisition_attempts(job_id=running.job_id) == ()


def test_recovery_records_retryable_current_ordinal_with_stable_id(tmp_path: Path) -> None:
    store = AcquisitionStore(tmp_path / "acquisition.sqlite3")
    running = _running_job(store)

    recovered = store.recover_interrupted_jobs()

    assert len(recovered) == 1
    assert recovered[0].status is DownloadJobStatus.QUEUED
    assert recovered[0].attempts == running.attempts
    attempts = store.list_acquisition_attempts(job_id=running.job_id)
    assert len(attempts) == 1
    assert attempts[0].attempt_id == _download_attempt_id(running)
    assert attempts[0].ordinal == running.attempts
    assert attempts[0].outcome is AcquisitionAttemptOutcome.FAILED
    assert attempts[0].error_class == "interrupted_restart"
    assert attempts[0].retryable is True
    assert store.recover_interrupted_jobs() == ()
    assert store.list_acquisition_attempts(job_id=running.job_id) == attempts


@pytest.mark.asyncio
async def test_run_download_preflight_failure_never_enters_running(tmp_path: Path) -> None:
    store = AcquisitionStore(tmp_path / "acquisition.sqlite3")
    queued = store.save_download_job(_job(status=DownloadJobStatus.QUEUED))
    service = LiteratureAcquisitionService(
        store,
        registry=SourceRegistry((ArxivSourceAdapter(),)),
        project_path=lambda _project_id, *parts: tmp_path.joinpath(*parts),
        validate_project=lambda _project_id: None,
    )

    with pytest.raises(AcquisitionNotFoundError, match="Candidate not found"):
        await service.run_download(queued.job_id)

    assert store.get_download_job(queued.job_id) == queued
    assert queued.status is DownloadJobStatus.QUEUED
    assert queued.attempts == 0
    assert store.list_acquisition_attempts(job_id=queued.job_id) == ()


@pytest.mark.asyncio
async def test_recovered_unproved_final_pdf_fails_closed_without_network(tmp_path: Path) -> None:
    store = AcquisitionStore(tmp_path / "acquisition.sqlite3")
    candidate = _candidate()
    _store_candidate(store, candidate)
    project_root = tmp_path / "project"

    def reject_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected network request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(reject_network))
    service = LiteratureAcquisitionService(
        store,
        registry=SourceRegistry((ArxivSourceAdapter(),)),
        project_path=lambda _project_id, *parts: project_root.joinpath(*parts),
        validate_project=lambda _project_id: None,
        download_client=client,
        resolver=lambda _host: ("93.184.216.34",),
    )
    try:
        queued = service.queue_download(
            project_id=candidate.project_id,
            candidate_id=candidate.candidate_id,
            access_evidence_id="access_fixture",
        )
        running = store.transition_download_job(
            queued.job_id,
            expected_version=queued.version,
            from_statuses=(DownloadJobStatus.QUEUED,),
            to_status=DownloadJobStatus.RUNNING,
        )
        target = project_root.joinpath(*Path(running.artifact_path).parts)
        payload = _pdf_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        recovered = store.recover_interrupted_jobs()

        assert len(recovered) == 1
        failed = await service.run_download(recovered[0].job_id)
        assert failed.status is DownloadJobStatus.FAILED
        assert failed.error_code == "artifact_proof_missing"
        assert failed.artifact_id is None
        assert target.read_bytes() == payload
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_service_resumes_persisted_partial_with_exact_range_after_restart(
    tmp_path: Path,
) -> None:
    payload = _pdf_bytes()
    partial_size = len(payload) // 2
    db_path = tmp_path / "acquisition.sqlite3"
    initial_store = AcquisitionStore(db_path)
    candidate = _candidate()
    _store_candidate(initial_store, candidate)
    project_root = tmp_path / "project"
    initial_service = LiteratureAcquisitionService(
        initial_store,
        registry=SourceRegistry((ArxivSourceAdapter(),)),
        project_path=lambda _project_id, *parts: project_root.joinpath(*parts),
        validate_project=lambda _project_id: None,
    )
    queued = initial_service.queue_download(
        project_id=candidate.project_id,
        candidate_id=candidate.candidate_id,
        access_evidence_id="access_fixture",
    )
    running = initial_store.transition_download_job(
        queued.job_id,
        expected_version=queued.version,
        from_statuses=(DownloadJobStatus.QUEUED,),
        to_status=DownloadJobStatus.RUNNING,
    )
    target = project_root.joinpath(*Path(running.artifact_path).parts)
    part = target.with_name(f"{target.name}.part")
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(payload[:partial_size])

    def _resume_response(request: httpx.Request) -> httpx.Response:
        assert request.url == running.source_url
        assert request.headers.get("range") == f"bytes={partial_size}-"
        remaining = payload[partial_size:]
        return httpx.Response(
            206,
            headers={
                "content-type": "application/pdf",
                "content-length": str(len(remaining)),
                "content-range": f"bytes {partial_size}-{len(payload) - 1}/{len(payload)}",
            },
            content=remaining,
        )

    reopened_store = AcquisitionStore(db_path)
    client = httpx.AsyncClient(transport=httpx.MockTransport(_resume_response))
    restarted_service = LiteratureAcquisitionService(
        reopened_store,
        registry=SourceRegistry((ArxivSourceAdapter(),)),
        project_path=lambda _project_id, *parts: project_root.joinpath(*parts),
        validate_project=lambda _project_id: None,
        download_client=client,
        resolver=lambda _host: ("93.184.216.34",),
    )
    try:
        recovered = restarted_service.recover_interrupted_jobs()
        assert len(recovered) == 1
        assert recovered[0].job_id == running.job_id
        assert recovered[0].status is DownloadJobStatus.QUEUED

        completed = await restarted_service.run_download(recovered[0].job_id)

        assert completed.status is DownloadJobStatus.COMPLETED
        assert completed.artifact_id is not None
        artifact = reopened_store.get_artifact(completed.artifact_id)
        assert artifact is not None
        assert artifact.sha256 == hashlib.sha256(payload).hexdigest()
        assert target.read_bytes() == payload
        assert not part.exists()
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "status",
    (DownloadJobStatus.QUEUED, DownloadJobStatus.PAUSED, DownloadJobStatus.FAILED),
)
def test_cancel_inactive_download_removes_persisted_partial(
    tmp_path: Path,
    status: DownloadJobStatus,
) -> None:
    store = AcquisitionStore(tmp_path / f"acquisition-{status.value}.sqlite3")
    project_root = tmp_path / status.value
    job = store.save_download_job(_job(status=status))
    target = project_root.joinpath(*Path(job.artifact_path).parts)
    part = target.with_name(f"{target.name}.part")
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"persisted partial bytes")
    service = LiteratureAcquisitionService(
        store,
        registry=SourceRegistry((ArxivSourceAdapter(),)),
        project_path=lambda _project_id, *parts: project_root.joinpath(*parts),
        validate_project=lambda _project_id: None,
    )

    cancelled = service.cancel_download(job.job_id)

    assert cancelled.status is DownloadJobStatus.CANCELLED
    assert not part.exists()


@pytest.mark.parametrize(
    "status",
    (DownloadJobStatus.RUNNING, DownloadJobStatus.VALIDATING),
)
def test_cancel_active_download_cleans_final_partial_and_prepared_proof(
    tmp_path: Path,
    status: DownloadJobStatus,
) -> None:
    store = AcquisitionStore(tmp_path / f"acquisition-{status.value}.sqlite3")
    running = _running_job(store)
    job = running
    if status is DownloadJobStatus.VALIDATING:
        job = store.transition_download_job(
            running.job_id,
            expected_version=running.version,
            from_statuses=(DownloadJobStatus.RUNNING,),
            to_status=DownloadJobStatus.VALIDATING,
        )
    project_root = tmp_path / status.value
    target = project_root.joinpath(*Path(job.artifact_path).parts)
    part = target.with_name(f"{target.name}.part")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _pdf_bytes()
    target.write_bytes(payload)
    part.write_bytes(b"stale partial")
    validation = validate_pdf_file(target)
    artifact = ValidatedArtifact(
        artifact_id=_stable_artifact_id(job.job_id, validation.sha256),
        job_id=job.job_id,
        project_id=job.project_id,
        candidate_id=job.candidate_id,
        relative_path=job.artifact_path,
        size_bytes=validation.size_bytes,
        sha256=validation.sha256,
        page_count=validation.page_count,
    )
    proof = store.save_artifact_promotion_proof(_promotion_proof(job, artifact))
    service = LiteratureAcquisitionService(
        store,
        registry=SourceRegistry((ArxivSourceAdapter(),)),
        project_path=lambda _project_id, *parts: project_root.joinpath(*parts),
        validate_project=lambda _project_id: None,
    )

    cancelled = service.cancel_download(job.job_id)

    assert cancelled.status is DownloadJobStatus.CANCELLED
    assert cancelled.bytes_downloaded == 0
    assert cancelled.error_code is None
    assert not target.exists()
    assert not part.exists()
    assert store.get_artifact_promotion_proof(proof.artifact_id) is None
    assert store.get_job_artifact_promotion_proof(job.job_id) is None


def test_cancel_cleanup_failure_is_persisted_and_retryable(tmp_path: Path) -> None:
    store = AcquisitionStore(tmp_path / "acquisition-cleanup-failure.sqlite3")
    project_root = tmp_path / "project"
    job = store.save_download_job(_job(status=DownloadJobStatus.QUEUED))
    target = project_root.joinpath(*Path(job.artifact_path).parts)
    target.mkdir(parents=True)
    service = LiteratureAcquisitionService(
        store,
        registry=SourceRegistry((ArxivSourceAdapter(),)),
        project_path=lambda _project_id, *parts: project_root.joinpath(*parts),
        validate_project=lambda _project_id: None,
    )

    with pytest.raises(AcquisitionConflictError) as exc_info:
        service.cancel_download(job.job_id)

    assert exc_info.value.code == "cancel_cleanup_failed"
    failed_cleanup = store.get_download_job(job.job_id)
    assert failed_cleanup is not None
    assert failed_cleanup.status is DownloadJobStatus.CANCELLED
    assert failed_cleanup.error_code == "cancel_cleanup_failed"
    target.rmdir()

    cleaned = service.cancel_download(job.job_id)

    assert cleaned.status is DownloadJobStatus.CANCELLED
    assert cleaned.error_code is None
    assert cleaned.error_message is None
    assert cleaned.bytes_downloaded == 0


@pytest.mark.asyncio
async def test_service_downloads_valid_oa_pdf_and_persists_artifact(tmp_path: Path) -> None:
    payload = _pdf_bytes()

    def _pdf_response(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://arxiv.org/pdf/2401.00001.pdf"
        return httpx.Response(
            200,
            headers={
                "content-type": "application/pdf",
                "content-length": str(len(payload)),
            },
            content=payload,
        )

    store = AcquisitionStore(tmp_path / "acquisition.sqlite3")
    candidate = _candidate()
    _store_candidate(store, candidate)
    project_root = tmp_path / "project"
    client = httpx.AsyncClient(transport=httpx.MockTransport(_pdf_response))
    service = LiteratureAcquisitionService(
        store,
        registry=SourceRegistry((ArxivSourceAdapter(),)),
        project_path=lambda _project_id, *parts: project_root.joinpath(*parts),
        validate_project=lambda _project_id: None,
        download_client=client,
        resolver=lambda _host: ("93.184.216.34",),
    )
    try:
        queued = service.queue_download(
            project_id=candidate.project_id,
            candidate_id=candidate.candidate_id,
            access_evidence_id="access_fixture",
        )
        completed = await service.run_download(queued.job_id)

        assert completed.status is DownloadJobStatus.COMPLETED
        assert completed.artifact_id is not None
        artifact = service.get_artifact(completed.artifact_id)
        assert artifact.sha256 == hashlib.sha256(payload).hexdigest()
        target = project_root.joinpath(*Path(completed.artifact_path).parts)
        assert target.read_bytes() == payload
        assert not target.with_name(f"{target.name}.part").exists()
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "content_type", "body", "expected_gate_type"),
    (
        (403, "text/html", b"<html>forbidden</html>", "http_403"),
        (200, "text/html", b"<html>sign in to continue</html>", "html_instead_of_pdf"),
    ),
)
async def test_service_stops_download_at_access_gate(
    tmp_path: Path,
    status_code: int,
    content_type: str,
    body: bytes,
    expected_gate_type: str,
) -> None:
    def _gate_response(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            headers={"content-type": content_type},
            content=body,
        )

    store = AcquisitionStore(tmp_path / f"acquisition-{expected_gate_type}.sqlite3")
    candidate = _candidate()
    _store_candidate(store, candidate)
    project_root = tmp_path / expected_gate_type
    client = httpx.AsyncClient(transport=httpx.MockTransport(_gate_response))
    service = LiteratureAcquisitionService(
        store,
        registry=SourceRegistry((ArxivSourceAdapter(),)),
        project_path=lambda _project_id, *parts: project_root.joinpath(*parts),
        validate_project=lambda _project_id: None,
        download_client=client,
        resolver=lambda _host: ("93.184.216.34",),
    )
    try:
        queued = service.queue_download(
            project_id=candidate.project_id,
            candidate_id=candidate.candidate_id,
            access_evidence_id="access_fixture",
        )
        gated = await service.run_download(queued.job_id)

        assert gated.status is DownloadJobStatus.HUMAN_REQUIRED
        assert gated.gate_id is not None
        gate = service.get_gate(gated.gate_id)
        assert gate.status.value == "open"
        assert gate.gate_type == expected_gate_type
        target = project_root.joinpath(*Path(gated.artifact_path).parts)
        assert not target.exists()
        assert not target.with_name(f"{target.name}.part").exists()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_import_receipt_is_idempotent(tmp_path: Path) -> None:
    store = AcquisitionStore(tmp_path / "acquisition.sqlite3")
    project_root = tmp_path / "project"
    source_path = project_root / "source_files" / "acquired_fixture.pdf"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(_pdf_bytes())
    validation = validate_pdf_file(source_path)
    artifact = _persist_validated_artifact(
        store,
        job_id="download_fixture",
        relative_path="source_files/acquired_fixture.pdf",
        validation=validation,
    )
    calls: list[Path] = []

    async def ingest_pdf(
        _project_id: str,
        local_path: Path,
        *,
        expected_sha256: str,
        expected_size: int,
    ) -> dict[str, object]:
        assert expected_sha256 == validation.sha256
        assert expected_size == validation.size_bytes
        calls.append(local_path)
        return {
            "material_id": "material_fixture",
            "status": "completed",
            "open_url": "/workbench/paper/material_fixture",
        }

    service = LiteratureAcquisitionService(
        store,
        project_path=lambda _project_id, *parts: project_root.joinpath(*parts),
        validate_project=lambda _project_id: None,
        ingest_pdf=ingest_pdf,
        verify_material_publication=_publication_evidence,
    )
    first = await service.import_artifact(artifact.artifact_id)
    second = await service.import_artifact(artifact.artifact_id)

    assert first == second
    assert first.status is ImportStatus.COMPLETED
    assert first.receipt_schema_version == "scholar-ai-import-receipt/v2"
    assert first.publication_state is ImportPublicationState.VERIFIED
    assert first.publication_evidence is not None
    assert calls == [source_path]
    assert service.get_artifact(artifact.artifact_id) == artifact
    assert service.get_download_job(artifact.job_id).artifact_id == artifact.artifact_id
    assert service.get_import_receipt(first.receipt_id) == first
    assert store.get_import_receipt(first.receipt_id) == first


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ingest_status", "expected_status"),
    (
        ("completed", ImportStatus.COMPLETED),
        ("duplicate", ImportStatus.DUPLICATE),
    ),
)
async def test_sync_import_persists_pending_receipt_before_publication_verification(
    tmp_path: Path,
    ingest_status: str,
    expected_status: ImportStatus,
) -> None:
    acquisition_db = tmp_path / f"acquisition-{ingest_status}.sqlite3"
    store = AcquisitionStore(acquisition_db)
    project_root = tmp_path / ingest_status
    source_path = project_root / "source_files" / f"acquired_{ingest_status}.pdf"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(_pdf_bytes())
    validation = validate_pdf_file(source_path)
    artifact = _persist_validated_artifact(
        store,
        job_id=f"download_sync_{ingest_status}",
        relative_path=f"source_files/acquired_{ingest_status}.pdf",
        validation=validation,
    )
    ingest_calls: list[Path] = []

    async def ingest_pdf(
        _project_id: str,
        local_path: Path,
        *,
        expected_sha256: str,
        expected_size: int,
    ) -> dict[str, object]:
        assert expected_sha256 == validation.sha256
        assert expected_size == validation.size_bytes
        ingest_calls.append(local_path)
        return {
            "material_id": f"material_sync_{ingest_status}",
            "status": ingest_status,
            "open_url": f"/workbench/paper/material_sync_{ingest_status}",
        }

    verification_attempts = 0

    def verify_after_retry(
        project_id: str,
        material_id: str,
        *,
        expected_source_fingerprint: str,
        expected_source_size: int,
    ) -> ImportPublicationEvidence:
        nonlocal verification_attempts
        verification_attempts += 1
        if verification_attempts == 1:
            raise RuntimeError("fixture publication stores are not converged")
        return _publication_evidence(
            project_id,
            material_id,
            expected_source_fingerprint=expected_source_fingerprint,
            expected_source_size=expected_source_size,
        )

    initial_service = LiteratureAcquisitionService(
        store,
        project_path=lambda _project_id, *parts: project_root.joinpath(*parts),
        validate_project=lambda _project_id: None,
        ingest_pdf=ingest_pdf,
        verify_material_publication=verify_after_retry,
    )

    pending = await initial_service.import_artifact(artifact.artifact_id)

    assert pending.status is expected_status
    assert pending.publication_state is ImportPublicationState.PENDING
    assert pending.publication_evidence is None
    assert pending.error_message == "Material publication verification is pending"
    assert store.get_import_receipt(pending.receipt_id) == pending

    async def reject_reingest(
        _project_id: str,
        _local_path: Path,
        *,
        expected_sha256: str,
        expected_size: int,
    ) -> dict[str, object]:
        raise AssertionError(
            f"unexpected reingest for {expected_sha256}:{expected_size}"
        )

    restarted_service = LiteratureAcquisitionService(
        AcquisitionStore(acquisition_db),
        project_path=lambda _project_id, *parts: project_root.joinpath(*parts),
        validate_project=lambda _project_id: None,
        ingest_pdf=reject_reingest,
        verify_material_publication=verify_after_retry,
    )

    reconciled = restarted_service.reconcile_import_receipts()

    assert len(reconciled) == 1
    verified = reconciled[0]
    assert verified.status is expected_status
    assert verified.publication_state is ImportPublicationState.VERIFIED
    assert verified.publication_evidence is not None
    assert verified.error_message is None
    assert verification_attempts == 2
    assert ingest_calls == [source_path]
    assert await restarted_service.import_artifact(artifact.artifact_id) == verified


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("terminal_source", "expected_status", "expected_error"),
    (
        ("task_completed", ImportStatus.COMPLETED, None),
        ("job_failed", ImportStatus.FAILED, "fixture extraction failed"),
    ),
)
async def test_queued_import_receipt_reconciles_after_runtime_restart(
    tmp_path: Path,
    terminal_source: str,
    expected_status: ImportStatus,
    expected_error: str | None,
) -> None:
    acquisition_db = tmp_path / "acquisition.sqlite3"
    runtime_db = tmp_path / "writing_runtime.sqlite3"
    store = AcquisitionStore(acquisition_db)
    project_root = tmp_path / "project"
    source_path = project_root / "source_files" / "acquired_restart_fixture.pdf"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(_pdf_bytes())
    validation = validate_pdf_file(source_path)
    artifact = _persist_validated_artifact(
        store,
        job_id=f"download_{terminal_source}",
        relative_path="source_files/acquired_restart_fixture.pdf",
        validation=validation,
    )

    runtime = WritingRuntime(database_path=runtime_db, autosave=True)
    session = runtime.create_session(mode=SessionMode.PROMPT)
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.PIPELINE_RUN,
        input_text="Extract acquired PDF",
        metadata={"project_id": artifact.project_id, "material_id": "material_restart"},
    )
    runtime.update_material_processing_task(
        job.job_id,
        request={
            "schema_version": "material_processing_task_v1",
            "project_id": artifact.project_id,
            "material_id": "material_restart",
            "input_ref": {
                "ref_type": "uploaded_source_file",
                "material_id": "material_restart",
                "source_path_label": source_path.name,
                "content_digest": f"sha256:{validation.sha256}",
                "size_bytes": validation.size_bytes,
            },
            "page_range": {"mode": "all", "pages": []},
            "processing_mode": "fast_text",
            "cache": {"policy": "use", "content_digest": f"sha256:{validation.sha256}"},
            "output_targets": ["chunks", "locators", "text_sidecar"],
            "metadata": {"source": "acquisition-restart-fixture"},
        },
        status="queued",
        provenance={"source": "pytest"},
    )
    ingest_calls: list[Path] = []

    async def queue_ingest(
        _project_id: str,
        local_path: Path,
        *,
        expected_sha256: str,
        expected_size: int,
    ) -> dict[str, object]:
        assert expected_sha256 == validation.sha256
        assert expected_size == validation.size_bytes
        ingest_calls.append(local_path)
        return {
            "material_id": "material_restart",
            "status": "queued",
            "session_id": session.session_id,
            "job_id": job.job_id,
            "open_url": "/workbench/paper/material_restart",
        }

    initial_service = LiteratureAcquisitionService(
        store,
        project_path=lambda _project_id, *parts: project_root.joinpath(*parts),
        validate_project=lambda _project_id: None,
        ingest_pdf=queue_ingest,
        verify_material_publication=_publication_evidence,
        runtime_reader=runtime,
    )
    queued_receipt = await initial_service.import_artifact(artifact.artifact_id)
    assert queued_receipt.status is ImportStatus.QUEUED

    if terminal_source == "task_completed":
        runtime.record_material_processing_task_result(
            job.job_id,
            status="completed",
            result={"status": "completed", "chunks": 1},
            provenance={"source": "pytest"},
        )
    else:
        await runtime.fail_job(job.job_id, "fixture extraction failed")

    restarted_runtime = WritingRuntime(database_path=runtime_db, autosave=True)

    async def reject_reingest(
        _project_id: str,
        _local_path: Path,
        *,
        expected_sha256: str,
        expected_size: int,
    ) -> dict[str, object]:
        raise AssertionError(
            f"unexpected reingest for {expected_sha256}:{expected_size}"
        )

    restarted_service = LiteratureAcquisitionService(
        AcquisitionStore(acquisition_db),
        project_path=lambda _project_id, *parts: project_root.joinpath(*parts),
        validate_project=lambda _project_id: None,
        ingest_pdf=reject_reingest,
        verify_material_publication=_publication_evidence,
        runtime_reader=restarted_runtime,
    )
    if terminal_source == "task_completed":
        reconciled = restarted_service.reconcile_import_receipts()
        assert len(reconciled) == 1
        repeated = await restarted_service.import_artifact(artifact.artifact_id)
        assert reconciled[0] == repeated
    else:
        repeated = await restarted_service.import_artifact(artifact.artifact_id)
        assert restarted_service.get_import_receipt(repeated.receipt_id) == repeated

    assert repeated.status is expected_status
    assert repeated.error_message == expected_error
    assert repeated.publication_state is (
        ImportPublicationState.VERIFIED
        if expected_status is ImportStatus.COMPLETED
        else ImportPublicationState.FAILED
    )
    assert repeated.version == queued_receipt.version + 1
    assert restarted_service.reconcile_import_receipts() == ()
    assert ingest_calls == [source_path]


@pytest.mark.asyncio
async def test_runtime_completion_waits_for_publication_verifier_then_retries(
    tmp_path: Path,
) -> None:
    store = AcquisitionStore(tmp_path / "acquisition.sqlite3")
    project_root = tmp_path / "project"
    source_path = project_root / "source_files" / "acquired_publication_retry.pdf"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(_pdf_bytes())
    validation = validate_pdf_file(source_path)
    artifact = _persist_validated_artifact(
        store,
        job_id="download_publication_retry",
        relative_path="source_files/acquired_publication_retry.pdf",
        validation=validation,
    )

    runtime = WritingRuntime(database_path=tmp_path / "writing_runtime.sqlite3", autosave=True)
    session = runtime.create_session(mode=SessionMode.PROMPT)
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.PIPELINE_RUN,
        input_text="Publish acquired PDF",
        metadata={"project_id": artifact.project_id, "material_id": "material_retry"},
    )
    ingest_calls: list[Path] = []

    async def queue_ingest(
        _project_id: str,
        local_path: Path,
        *,
        expected_sha256: str,
        expected_size: int,
    ) -> dict[str, object]:
        assert expected_sha256 == validation.sha256
        assert expected_size == validation.size_bytes
        ingest_calls.append(local_path)
        return {
            "material_id": "material_retry",
            "status": "queued",
            "session_id": session.session_id,
            "job_id": job.job_id,
            "open_url": "/workbench/paper/material_retry",
        }

    verification_attempts = 0

    def verify_after_retry(
        project_id: str,
        material_id: str,
        *,
        expected_source_fingerprint: str,
        expected_source_size: int,
    ) -> ImportPublicationEvidence:
        nonlocal verification_attempts
        verification_attempts += 1
        if verification_attempts == 1:
            raise RuntimeError("fixture publication stores are not converged")
        return _publication_evidence(
            project_id,
            material_id,
            expected_source_fingerprint=expected_source_fingerprint,
            expected_source_size=expected_source_size,
        )

    service = LiteratureAcquisitionService(
        store,
        project_path=lambda _project_id, *parts: project_root.joinpath(*parts),
        validate_project=lambda _project_id: None,
        ingest_pdf=queue_ingest,
        verify_material_publication=verify_after_retry,
        runtime_reader=runtime,
    )
    queued = await service.import_artifact(artifact.artifact_id)
    assert queued.status is ImportStatus.QUEUED
    assert queued.publication_state is ImportPublicationState.PENDING

    await runtime.complete_job(job.job_id, result={"status": "completed"})
    first_pass = service.reconcile_import_receipts()

    assert len(first_pass) == 1
    pending = first_pass[0]
    assert pending.status is ImportStatus.QUEUED
    assert pending.publication_state is ImportPublicationState.PENDING
    assert pending.publication_evidence is None
    assert pending.error_message == "Material publication verification is pending"
    assert pending.version == queued.version + 1

    verified = service.get_import_receipt(pending.receipt_id)

    assert verified.status is ImportStatus.COMPLETED
    assert verified.publication_state is ImportPublicationState.VERIFIED
    assert verified.publication_evidence is not None
    assert verified.error_message is None
    assert verified.version == pending.version + 1
    assert verification_attempts == 2
    assert service.reconcile_import_receipts() == ()
    assert store.get_import_receipt(verified.receipt_id) == verified
    assert ingest_calls == [source_path]


@pytest.mark.asyncio
async def test_offline_acquisition_e2e_reconciles_material_after_runtime_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = "project_acquisition_e2e"
    project_root = tmp_path / project_id
    acquisition_db = tmp_path / "acquisition-e2e.sqlite3"
    runtime_db = tmp_path / "writing-runtime-e2e.sqlite3"
    payload = _pdf_bytes()
    repository_policy = SourcePolicy(
        source_id="fixture_repository",
        capabilities=("search", "download"),
        metadata_hosts=("metadata.fixture.example",),
        download_hosts=("files.fixture.example",),
        evidence_kinds=(AccessEvidenceKind.OFFICIAL_REPOSITORY,),
        min_interval_seconds=0,
        terms_url="https://metadata.fixture.example/terms",
    )

    class _ArxivFixtureSource:
        policy = ARXIV_POLICY

        async def search(
            self,
            query: SearchQuery,
            *,
            run_id: str,
        ) -> tuple[CandidateManifest, ...]:
            return (
                _candidate().model_copy(
                    update={"run_id": run_id, "project_id": query.project_id}
                ),
            )

    class _RepositoryFixtureSource:
        policy = repository_policy

        async def search(
            self,
            query: SearchQuery,
            *,
            run_id: str,
        ) -> tuple[CandidateManifest, ...]:
            candidate_id = "cand_fixture_repository_e2e"
            pdf_url = "https://files.fixture.example/paper.pdf"
            evidence = AccessEvidence(
                evidence_id="access_fixture_repository_e2e",
                candidate_id=candidate_id,
                source_platform=repository_policy.source_id,
                kind=AccessEvidenceKind.OFFICIAL_REPOSITORY,
                access_route=AccessRoute.OPEN_ACCESS,
                pdf_url=pdf_url,
                statement="Fixture repository provides the open-access PDF.",
            )
            return (
                CandidateManifest(
                    candidate_id=candidate_id,
                    run_id=run_id,
                    project_id=query.project_id,
                    title="Shared title",
                    authors=("Example, Alice",),
                    year=2024,
                    arxiv_id="2401.00001",
                    source_platforms=(repository_policy.source_id,),
                    pdf_candidates=(
                        PdfCandidate(
                            pdf_url=pdf_url,
                            source_platform=repository_policy.source_id,
                            access_evidence=evidence,
                        ),
                    ),
                ),
            )

    def fixture_project_path(
        requested_project_id: str,
        *parts: str,
    ) -> Path:
        assert requested_project_id == project_id
        return project_root.joinpath(*parts)

    def validate_project(requested_project_id: str) -> None:
        assert requested_project_id == project_id

    class _Material:
        material_id = "material_acquisition_e2e"

    created_materials: list[dict[str, object]] = []

    class _ResourceStore:
        def create_material(self, **kwargs: object) -> _Material:
            assert kwargs["project_id"] == project_id
            created_materials.append(dict(kwargs))
            return _Material()

    resource_store = _ResourceStore()

    def ensure_project(requested_project_id: str) -> _ResourceStore:
        assert requested_project_id == project_id
        return resource_store

    extraction_calls: list[Path] = []

    def extract_fixture(
        filename: str,
        source_path: Path,
        *,
        project_id: str | None = None,
    ) -> resources_router.ExtractedDocumentPayload:
        assert project_id == "project_acquisition_e2e"
        assert filename.endswith(".pdf")
        extraction_calls.append(source_path)
        return resources_router.ExtractedDocumentPayload(
            content=(
                "Offline acquisition fixture evidence. "
                "The validated source is indexed into durable project chunks."
            )
        )

    runtime = WritingRuntime(database_path=runtime_db, autosave=True)
    monkeypatch.setattr(resources_router, "project_data_path", fixture_project_path)
    monkeypatch.setattr(resources_router, "_ensure_upload_project", ensure_project)
    monkeypatch.setattr(
        resources_router,
        "_extract_document_payload_from_path",
        extract_fixture,
    )
    monkeypatch.setattr("writing_runtime.get_writing_runtime", lambda: runtime)
    monkeypatch.setattr(resources_router, "_DOC_STORE_DIR", tmp_path / "legacy-doc-store")
    monkeypatch.setattr(resources_router, "_CHUNK_STORE_DIR", tmp_path / "legacy-chunk-store")

    network_requests: list[httpx.Request] = []

    def pdf_response(request: httpx.Request) -> httpx.Response:
        network_requests.append(request)
        assert request.url == "https://arxiv.org/pdf/2401.00001.pdf"
        return httpx.Response(
            200,
            headers={
                "content-type": "application/pdf",
                "content-length": str(len(payload)),
            },
            content=payload,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(pdf_response))
    service = LiteratureAcquisitionService(
        AcquisitionStore(acquisition_db),
        registry=SourceRegistry((_ArxivFixtureSource(), _RepositoryFixtureSource())),
        project_path=fixture_project_path,
        validate_project=validate_project,
        ingest_pdf=resources_router.ingest_validated_pdf_path,
        download_client=client,
        resolver=lambda _host: ("93.184.216.34",),
        runtime_reader=runtime,
    )
    try:
        run = await service.search(
            SearchQuery(
                project_id=project_id,
                query="shared paper",
                sources=("arxiv", repository_policy.source_id),
                max_results=5,
            )
        )
        assert run.status is SearchRunStatus.COMPLETED
        assert len(run.candidates) == 1
        candidate = run.candidates[0]
        assert candidate.source_platforms == ("arxiv", repository_policy.source_id)
        assert candidate.merged_from_candidate_ids == ("cand_fixture_repository_e2e",)
        assert {item.access_evidence.access_route for item in candidate.pdf_candidates} == {
            AccessRoute.OPEN_ACCESS
        }
        identity_receipts = service.list_identity_merge_receipts(run.run_id)
        assert len(identity_receipts) == 1
        assert identity_receipts[0].outcome is IdentityDecisionOutcome.MATCH
        assert identity_receipts[0].method is IdentityMatchMethod.ARXIV_ID

        queued = service.queue_download(
            project_id=project_id,
            candidate_id=candidate.candidate_id,
            access_evidence_id="access_fixture",
        )
        completed = await service.run_download(queued.job_id)
        assert completed.status is DownloadJobStatus.COMPLETED
        assert completed.artifact_id is not None
        artifact = service.get_artifact(completed.artifact_id)
        assert artifact.sha256 == hashlib.sha256(payload).hexdigest()
        assert artifact.page_count == 1

        queued_receipt = await service.import_artifact(artifact.artifact_id)
        assert queued_receipt.status is ImportStatus.QUEUED
        assert queued_receipt.runtime_job_id is not None
        assert queued_receipt.runtime_session_id is not None
        assert queued_receipt.material_id == _Material.material_id

        async def wait_for_runtime_terminal() -> None:
            while True:
                job = runtime.get_job(queued_receipt.runtime_job_id or "")
                assert job is not None
                if job.status.value in {"completed", "failed", "cancelled"}:
                    assert job.status.value == "completed"
                    return
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_runtime_terminal(), timeout=5)
        doc_store = resources_router._load_doc_store(project_id)
        chunk_store = resources_router._load_chunk_store(project_id)
        assert created_materials and created_materials[0]["title"].endswith(".pdf")
        assert doc_store[_Material.material_id]["extraction_status"] == "succeeded"
        assert "Offline acquisition fixture evidence" in doc_store[_Material.material_id]["content"]
        assert chunk_store[_Material.material_id]
        assert all(
            chunk["material_id"] == _Material.material_id
            for chunk in chunk_store[_Material.material_id]
        )

        restarted_runtime = WritingRuntime(database_path=runtime_db, autosave=True)

        async def reject_reingest(
            _project_id: str,
            _local_path: Path,
            *,
            expected_sha256: str,
            expected_size: int,
        ) -> dict[str, object]:
            raise AssertionError(
                f"unexpected reingest for {expected_sha256}:{expected_size}"
            )

        restarted_service = LiteratureAcquisitionService(
            AcquisitionStore(acquisition_db),
            project_path=fixture_project_path,
            validate_project=lambda _project_id: None,
            ingest_pdf=reject_reingest,
            runtime_reader=restarted_runtime,
        )
        reconciled = restarted_service.reconcile_import_receipts()
        assert len(reconciled) == 1
        assert reconciled[0].receipt_id == queued_receipt.receipt_id
        assert reconciled[0].status is ImportStatus.COMPLETED
        assert reconciled[0].version == queued_receipt.version + 1
        assert await restarted_service.import_artifact(artifact.artifact_id) == reconciled[0]
        assert restarted_service.reconcile_import_receipts() == ()
        restarted_task = restarted_runtime.get_material_processing_task(
            queued_receipt.runtime_job_id
        )
        assert restarted_task is not None
        assert restarted_task["status"] == "completed"
        assert extraction_calls == [project_root / artifact.relative_path]
        assert len(network_requests) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_validated_pdf_ingest_reuses_resource_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = "project_fixture"
    source_root = tmp_path / project_id / "source_files"
    source_root.mkdir(parents=True)
    source_path = source_root / "acquired_fixture.pdf"
    source_path.write_bytes(_pdf_bytes())
    validation = validate_pdf_file(source_path)

    class _Material:
        material_id = "material_fixture"

    class _Store:
        def create_material(self, **kwargs: object) -> _Material:
            assert kwargs["project_id"] == project_id
            return _Material()

    monkeypatch.setattr(resources_router, "_ensure_upload_project", lambda _project_id: _Store())
    monkeypatch.setattr(
        resources_router,
        "project_data_path",
        lambda requested_project_id, *parts: tmp_path / requested_project_id / Path(*parts),
    )
    monkeypatch.setattr(resources_router, "_load_doc_store", lambda _project_id: {})
    monkeypatch.setattr(resources_router, "_save_doc_store", lambda *_args: None)
    monkeypatch.setattr(resources_router, "_load_chunk_store", lambda _project_id: {})
    monkeypatch.setattr(resources_router, "_save_chunk_store", lambda *_args: None)

    async def _start_job(
        requested_project_id: str,
        material_id: str,
        filename: str,
        queued_source_path: Path,
        *,
        source_fingerprint: str,
        source_size: int,
        source_relative_path: str | None = None,
        batch_context: resources_router._UploadBatchContext | None = None,
    ) -> tuple[str, str]:
        assert requested_project_id == project_id
        assert material_id == "material_fixture"
        assert filename == source_path.name
        assert queued_source_path == source_path
        assert source_fingerprint == f"sha256:{validation.sha256}"
        assert source_size == validation.size_bytes
        assert source_relative_path == source_path.name
        assert batch_context is None
        return "session_fixture", "job_fixture"

    monkeypatch.setattr(resources_router, "_start_uploaded_document_extraction_job", _start_job)

    result = await resources_router.ingest_validated_pdf_path(
        project_id,
        source_path,
        expected_sha256=validation.sha256,
        expected_size=validation.size_bytes,
    )

    assert result["material_id"] == "material_fixture"
    assert result["status"] == "queued"
    assert result["session_id"] == "session_fixture"
    assert result["job_id"] == "job_fixture"


@pytest.mark.asyncio
async def test_validated_pdf_ingest_rejects_path_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "outside.pdf"
    source_path.write_bytes(_pdf_bytes())
    validation = validate_pdf_file(source_path)
    monkeypatch.setattr(resources_router, "_ensure_upload_project", lambda _project_id: object())
    monkeypatch.setattr(
        resources_router,
        "project_data_path",
        lambda project_id, *parts: tmp_path / project_id / Path(*parts),
    )

    with pytest.raises(ValueError, match="source_files"):
        await resources_router.ingest_validated_pdf_path(
            "project_fixture",
            source_path,
            expected_sha256=validation.sha256,
            expected_size=validation.size_bytes,
        )


def test_acquisition_http_adapter_reuses_one_service(tmp_path: Path) -> None:
    class _FixtureSource:
        policy = ARXIV_POLICY

        async def search(self, query: SearchQuery, *, run_id: str) -> tuple[CandidateManifest, ...]:
            return (
                _candidate().model_copy(
                    update={
                        "run_id": run_id,
                        "project_id": query.project_id,
                    }
                ),
            )

    service = LiteratureAcquisitionService(
        AcquisitionStore(tmp_path / "acquisition.sqlite3"),
        registry=SourceRegistry((_FixtureSource(),)),
        project_path=lambda _project_id, *parts: tmp_path.joinpath(*parts),
        validate_project=lambda _project_id: None,
    )
    app = FastAPI()
    app.include_router(acquisition_router.router)
    app.dependency_overrides[acquisition_router.get_acquisition_service] = lambda: service

    with TestClient(app) as client:
        search_response = client.post(
            "/api/acquisition/search",
            json={
                "project_id": "project_fixture",
                "query": "fixture",
                "sources": ["arxiv"],
                "max_results": 5,
            },
        )
        assert search_response.status_code == 200
        search_run = search_response.json()
        candidate = search_run["candidates"][0]

        identity_response = client.get(
            f"/api/acquisition/search-runs/{search_run['run_id']}/identity-ledger",
            params={"limit": 1},
        )
        assert identity_response.status_code == 200
        assert identity_response.json() == {
            "run_id": search_run["run_id"],
            "project_id": "project_fixture",
            "identity_receipts": [],
            "version_relations": [],
        }

        queue_response = client.post(
            "/api/acquisition/downloads",
            json={
                "project_id": "project_fixture",
                "candidate_id": candidate["candidate_id"],
                "access_evidence_id": candidate["pdf_candidates"][0]["access_evidence"]["evidence_id"],
            },
        )
        assert queue_response.status_code == 200
        assert queue_response.json()["status"] == "queued"

        job_response = client.get(
            f"/api/acquisition/downloads/{queue_response.json()['job_id']}"
        )
        assert job_response.status_code == 200
        assert job_response.json() == queue_response.json()

        status_response = client.get(
            "/api/acquisition/status",
            params={"project_id": "project_fixture"},
        )
        assert status_response.status_code == 200
        assert [source["source_id"] for source in status_response.json()["sources"]] == ["arxiv"]
        assert [job["job_id"] for job in status_response.json()["download_jobs"]] == [
            queue_response.json()["job_id"]
        ]

        denied_response = client.post(
            "/api/acquisition/downloads",
            json={
                "project_id": "project_fixture",
                "candidate_id": candidate["candidate_id"],
                "access_evidence_id": "access_missing",
            },
        )
        assert denied_response.status_code == 403
        assert denied_response.json()["detail"]["code"] == "access_evidence_not_found"

        missing_routes = {
            "/api/acquisition/downloads/download_missing": "download_job_not_found",
            "/api/acquisition/gates/gate_missing": "access_gate_not_found",
            "/api/acquisition/artifacts/artifact_missing": "validated_artifact_not_found",
            "/api/acquisition/receipts/receipt_missing": "import_receipt_not_found",
        }
        for path, expected_code in missing_routes.items():
            missing_response = client.get(path)
            assert missing_response.status_code == 404
            assert missing_response.json()["detail"]["code"] == expected_code


def test_acquisition_http_receipt_routes_preserve_publication_proof() -> None:
    evidence = _publication_evidence(
        "project_fixture",
        "material_fixture",
        expected_source_fingerprint=f"sha256:{'a' * 64}",
        expected_source_size=4096,
    )
    receipt = ImportReceipt(
        receipt_id="import_fixture",
        artifact_id="artifact_fixture",
        project_id="project_fixture",
        candidate_id="candidate_fixture",
        material_id="material_fixture",
        status=ImportStatus.COMPLETED,
        source_fingerprint=f"sha256:{'a' * 64}",
        receipt_schema_version="scholar-ai-import-receipt/v2",
        publication_state=ImportPublicationState.VERIFIED,
        publication_evidence=evidence,
        open_url="/workbench/paper/material_fixture",
    )

    class _ReceiptService:
        async def import_artifact(self, artifact_id: str) -> ImportReceipt:
            assert artifact_id == receipt.artifact_id
            return receipt

        def get_import_receipt(self, receipt_id: str) -> ImportReceipt:
            assert receipt_id == receipt.receipt_id
            return receipt

    app = FastAPI()
    app.include_router(acquisition_router.router)
    app.dependency_overrides[acquisition_router.get_acquisition_service] = _ReceiptService
    expected = receipt.model_dump(mode="json")

    with TestClient(app) as client:
        imported = client.post(f"/api/acquisition/artifacts/{receipt.artifact_id}/import")
        read_back = client.get(f"/api/acquisition/receipts/{receipt.receipt_id}")

    assert imported.status_code == 200
    assert read_back.status_code == 200
    assert imported.json() == expected
    assert read_back.json() == expected
    assert read_back.json()["publication_state"] == "verified"
    assert read_back.json()["publication_evidence"]["evidence_fingerprint"] == (
        evidence.evidence_fingerprint
    )


@pytest.mark.asyncio
async def test_416_requires_proof_that_partial_is_complete(tmp_path: Path) -> None:
    target = tmp_path / "source_files" / "paper.pdf"
    target.parent.mkdir(parents=True)
    part = target.with_name(f"{target.name}.part")
    payload = _pdf_bytes()
    part.write_bytes(payload)

    invalid_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(416))
    )
    try:
        with pytest.raises(DownloadTransferError, match="did not prove"):
            await download_validated_pdf(
                source_url="https://arxiv.org/pdf/2401.00001.pdf",
                policy=ARXIV_POLICY,
                destination=target,
                project_root=tmp_path,
                client=invalid_client,
                resolver=lambda _host: ("93.184.216.34",),
            )
    finally:
        await invalid_client.aclose()

    valid_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                416,
                headers={"Content-Range": f"bytes */{len(payload)}"},
            )
        )
    )
    try:
        downloaded = await download_validated_pdf(
            source_url="https://arxiv.org/pdf/2401.00001.pdf",
            policy=ARXIV_POLICY,
            destination=target,
            project_root=tmp_path,
            client=valid_client,
            resolver=lambda _host: ("93.184.216.34",),
        )
        assert downloaded.path == target
        assert downloaded.validation.sha256 == hashlib.sha256(payload).hexdigest()
        assert target.read_bytes() == payload
        assert not part.exists()
    finally:
        await valid_client.aclose()
