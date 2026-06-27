"""Evidence chain and source labels API router - /api/evidence_refs, /api/source_labels.

Provides independent evidence_refs API with source_labels filtering (A4/A5),
chunk locator bbox support (A7), discussion evidence_pack persistence (D5),
and citation overlap detection (D8).
"""

from fastapi import APIRouter, HTTPException, Query, Response
from typing import Any, Callable, List, Literal, Optional
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel, Field, ValidationError
import csv
import io
import json
import os
import re
import uuid

import routers.resources_router as _resources_router
from literature_assistant.core.chunk_package_quality import default_joint_recall_policy, weighted_rrf_fuse
from literature_assistant.core.academic_english_resources import search_academic_english
from literature_assistant.core.config_knowledge import search_scoring_rules
from literature_assistant.core.product_docs_knowledge import search_product_docs
from literature_assistant.core.source_vault import (
    SourceVault,
    build_source_vault_chunk_read_endpoint,
    build_source_vault_chunk_ref_id,
    build_source_vault_search_metadata,
)
from literature_assistant.core.skill_package_knowledge import ACADEMIC_ENGLISH_SKILL_PACKAGE_ID, search_skill_package
from literature_assistant.core.project_paths import wiki_generated_root, wiki_query_index_path
from literature_assistant.core.runtime_env import wiki_enabled
from literature_assistant.core.wiki.page_store import WikiPageStore
from literature_assistant.core.wiki.query import WikiQueryIndex, build_knowledge_refs
from project_paths import project_data_path, runtime_state_path
from routers.resources_router.endpoints_search_upload import (
    build_locator_coverage,
    _chunk_to_search_ref,
    _flatten_chunk_store_for_search_refs,
    enrich_chunk_locator_with_pdf,
    find_chunk_locator,
)
from models import (
    PdfAnchorFields,
    PdfBboxUnit,
    coerce_pdf_bbox,
    pdf_bbox_matches_unit,
    SourceLabelPayload,
    CreateSourceLabelRequest,
    UpdateSourceLabelRequest,
    EvidenceRefPayload,
    EvidenceRefsResponse,
    ChunkLocatorPayload,
    DiscussionEvidencePackPayload,
    EvidencePackBuildRequest,
    EvidencePackBuildResponse,
    EvidencePackReferencePayload,
    EvidenceRetrievalDiagnosticsPayload,
    RetrievalQrelsStatusPayload,
    ToolAttempt,
    ToolNextAction,
    ToolOutcome,
    CitationOverlapPayload,
    CitationVerificationPayload,
    CitationVerificationRequest,
    CitationVerificationStatus,
    CitationVerificationsResponse,
)

router = APIRouter(tags=["Evidence"])


# In-memory stores (TODO: replace with persistent storage)
_source_labels_store: dict[str, SourceLabelPayload] = {}
_evidence_refs_store: dict[str, EvidenceRefPayload] = {}
_discussion_packs_store: dict[str, DiscussionEvidencePackPayload] = {}
_citation_verifications_store: dict[str, CitationVerificationPayload] = {}
_SOURCE_LABELS_VERSION = 1
_EVIDENCE_REFS_VERSION = 1
_DISCUSSION_EVIDENCE_PACKS_VERSION = 1
_CITATION_VERIFICATIONS_VERSION = 1
_EVIDENCE_REFS_EXPORT_VERSION = 1
_EVIDENCE_PACK_SUMMARY_CHARS = 300
_EVIDENCE_REFS_EXPORT_CSV_FIELDS: tuple[str, ...] = (
    "ref_id",
    "chunk_id",
    "material_id",
    "page",
    "bbox",
    "bbox_unit",
    "source",
    "source_label",
    "source_labels",
    "label",
    "score",
    "rank",
    "source_hint",
    "text",
    "quote",
    "compressed_text",
    "created_at",
    "updated_at",
)
_CANDIDATE_QRELS_FILENAMES: tuple[str, ...] = (
    "qrels_candidate.trec",
    "candidate.qrels",
    "candidate_qrels.trec",
)
_REVIEWED_QRELS_FILENAMES: tuple[str, ...] = (
    "goldset_reviewed.jsonl",
    "reviewed.jsonl",
    "goldset_review_template.jsonl",
)
_CANONICAL_QRELS_FILENAMES: tuple[str, ...] = (
    "canonical.qrels",
    "canonical.trec",
    "qrels.trec",
    "goldset.qrels",
)
KnowledgeRefSourceType = Literal[
    "product_docs",
    "scoring_rules",
    "academic_english",
    "skill_package",
    "source_vault",
]

_EVIDENCE_PACK_KNOWLEDGE_REF_KINDS: tuple[KnowledgeRefSourceType, ...] = (
    "product_docs",
    "scoring_rules",
    "academic_english",
    "skill_package",
    "source_vault",
)
_EVIDENCE_PACK_MAX_KNOWLEDGE_REFS = len(_EVIDENCE_PACK_KNOWLEDGE_REF_KINDS)


def _count_trec_qrels_rows(path: Path) -> int:
    """Return non-comment TREC qrels row count from a bounded local file."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) >= 4:
            count += 1
    return count


def _count_reviewed_qrels_rows(path: Path) -> int:
    """Return reviewed judgment rows that no longer carry an unknown label."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        judgment = str(row.get("judgment") or "").strip().lower()
        if judgment and judgment != "unknown":
            count += 1
    return count


def _sum_named_files(root: Path, filenames: tuple[str, ...], counter: Any) -> int:
    """Count rows from direct known files without recursive workspace scans."""

    total = 0
    for filename in filenames:
        candidate = root / filename
        if candidate.is_file():
            total += int(counter(candidate))
    return total


def _project_qrels_status(project_id: str) -> RetrievalQrelsStatusPayload:
    """Return the highest local qrels review state for evidence-pack claims.

    Args:
        project_id: Project id whose generated qrels sidecars are inspected.

    Returns:
        A quality-gate payload. It never creates, promotes, deletes, or mutates
        qrels artifacts; missing/malformed local files degrade to zero counts.
    """

    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        raise ValueError("project_id must be non-empty")
    qrels_root = project_data_path(normalized_project_id, "qrels")
    candidate_count = _sum_named_files(
        qrels_root,
        _CANDIDATE_QRELS_FILENAMES,
        _count_trec_qrels_rows,
    )
    reviewed_count = _sum_named_files(
        qrels_root,
        _REVIEWED_QRELS_FILENAMES,
        _count_reviewed_qrels_rows,
    )
    canonical_count = _sum_named_files(
        qrels_root,
        _CANONICAL_QRELS_FILENAMES,
        _count_trec_qrels_rows,
    )
    if canonical_count > 0:
        return RetrievalQrelsStatusPayload(
            status="canonical",
            candidate_qrels_count=candidate_count,
            reviewed_qrels_count=reviewed_count,
            canonical_qrels_count=canonical_count,
            semantic_quality_claim_allowed=True,
            quality_claim="canonical_qrels_available",
            notes=[
                "Canonical qrels are available for offline retrieval-quality evaluation.",
            ],
        )
    if reviewed_count > 0:
        return RetrievalQrelsStatusPayload(
            status="reviewed",
            candidate_qrels_count=candidate_count,
            reviewed_qrels_count=reviewed_count,
            canonical_qrels_count=0,
            semantic_quality_claim_allowed=False,
            quality_claim="reviewed_qrels_promotion_required",
            notes=[
                "Reviewed judgments exist but have not been promoted to canonical qrels.",
            ],
        )
    if candidate_count > 0:
        return RetrievalQrelsStatusPayload(
            status="candidate",
            candidate_qrels_count=candidate_count,
            reviewed_qrels_count=0,
            canonical_qrels_count=0,
            semantic_quality_claim_allowed=False,
            quality_claim="candidate_qrels_review_required",
            notes=[
                "Candidate qrels require human review before semantic quality claims.",
            ],
        )
    return RetrievalQrelsStatusPayload(
        status="missing",
        candidate_qrels_count=0,
        reviewed_qrels_count=0,
        canonical_qrels_count=0,
        semantic_quality_claim_allowed=False,
        quality_claim="no_qrels_available",
        notes=[
            "No project qrels were found; retrieval method is provenance, not semantic quality proof.",
        ],
    )


def _evidence_runtime_store_path(filename: str) -> Path:
    """Return one evidence runtime JSON path under workspace_artifacts.

    Args:
        filename: Plain JSON filename. Path separators are rejected because
            callers should not be able to escape the evidence runtime store.

    Returns:
        Runtime-state path for a durable evidence sidecar store.

    Raises:
        ValueError: If filename is empty or path-like.
    """

    normalized = str(filename or "").strip()
    if not normalized or normalized != Path(normalized).name:
        raise ValueError("evidence store filename must be a plain filename")
    return runtime_state_path("evidence", normalized)


def _read_json_payload(path: Path) -> Any:
    """Read a JSON object or list; malformed stores degrade to an empty object."""

    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json_payload(path: Path, payload: dict[str, Any]) -> None:
    """Persist a runtime JSON payload with tmp+replace semantics."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Evidence runtime store write failed: {exc}") from exc


def _load_source_labels() -> dict[str, SourceLabelPayload]:
    """Load durable source labels and skip malformed records."""

    payload = _read_json_payload(_evidence_runtime_store_path("source_labels.json"))
    raw_labels = payload.get("labels") if isinstance(payload, dict) else payload
    if not isinstance(raw_labels, list):
        return {}

    labels: dict[str, SourceLabelPayload] = {}
    for raw_label in raw_labels:
        if not isinstance(raw_label, dict):
            continue
        try:
            label = SourceLabelPayload(**raw_label)
        except ValidationError:
            continue
        if label.label_id.strip():
            labels[label.label_id] = label
    return labels


def _write_source_labels(labels: dict[str, SourceLabelPayload]) -> None:
    """Persist source labels so label filters survive process restarts."""

    payload = {
        "version": _SOURCE_LABELS_VERSION,
        "labels": [
            label.model_dump(mode="json")
            for label in sorted(labels.values(), key=lambda item: (item.name.lower(), item.label_id))
        ],
    }
    _write_json_payload(_evidence_runtime_store_path("source_labels.json"), payload)


def _refresh_source_labels_store() -> dict[str, SourceLabelPayload]:
    """Merge durable source labels into the process cache."""

    _source_labels_store.update(_load_source_labels())
    return _source_labels_store


def _load_evidence_refs() -> dict[str, EvidenceRefPayload]:
    """Load durable evidence refs and skip malformed records."""

    payload = _read_json_payload(_evidence_runtime_store_path("evidence_refs.json"))
    raw_refs = payload.get("refs") if isinstance(payload, dict) else payload
    if not isinstance(raw_refs, list):
        return {}

    refs: dict[str, EvidenceRefPayload] = {}
    for raw_ref in raw_refs:
        if not isinstance(raw_ref, dict):
            continue
        try:
            ref = EvidenceRefPayload(**raw_ref)
        except ValidationError:
            continue
        if ref.ref_id.strip():
            refs[ref.ref_id] = ref
    return refs


def _write_evidence_refs(refs: dict[str, EvidenceRefPayload]) -> None:
    """Persist evidence refs with their source labels and PDF anchors."""

    payload = {
        "version": _EVIDENCE_REFS_VERSION,
        "refs": [
            ref.model_dump(mode="json")
            for ref in sorted(refs.values(), key=lambda item: (item.created_at, item.ref_id))
        ],
    }
    _write_json_payload(_evidence_runtime_store_path("evidence_refs.json"), payload)


def _refresh_evidence_refs_store() -> dict[str, EvidenceRefPayload]:
    """Merge durable evidence refs into the process cache."""

    _evidence_refs_store.update(_load_evidence_refs())
    return _evidence_refs_store


def _normalize_filter_values(values: Optional[List[str]]) -> list[str]:
    """Return stable non-empty filter values from repeated query params.

    Args:
        values: Query parameter values supplied by FastAPI.

    Returns:
        A deduplicated list preserving first-seen order.
    """

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values or []:
        value = str(raw_value or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _select_evidence_refs(
    *,
    material_id: Optional[str],
    source_labels: Optional[List[str]],
) -> list[EvidenceRefPayload]:
    """Select evidence refs with the same local filters used by export endpoints.

    Args:
        material_id: Optional material identifier to match exactly.
        source_labels: Optional labels; a ref matches when it has any label.

    Returns:
        Sorted evidence refs ready for pagination or export.
    """

    refs = list(_refresh_evidence_refs_store().values())
    normalized_material_id = str(material_id or "").strip()
    normalized_source_labels = _normalize_filter_values(source_labels)

    if normalized_material_id:
        refs = [ref for ref in refs if ref.material_id == normalized_material_id]

    if normalized_source_labels:
        refs = [
            ref
            for ref in refs
            if any(label in ref.source_labels for label in normalized_source_labels)
        ]

    return sorted(refs, key=lambda ref: (ref.created_at, ref.ref_id))


def _evidence_ref_export_row(ref: EvidenceRefPayload) -> dict[str, Any]:
    """Convert one evidence ref to a JSON-serializable export row."""

    return ref.model_dump(mode="json")


def _csv_cell(value: Any) -> str:
    """Serialize nested values without losing evidence anchor structure."""

    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _build_evidence_refs_export_payload(
    *,
    refs: list[EvidenceRefPayload],
    material_id: Optional[str],
    source_labels: Optional[List[str]],
) -> dict[str, Any]:
    """Build the deterministic JSON evidence refs export envelope.

    Args:
        refs: Filtered evidence refs to export.
        material_id: Material filter supplied by the caller.
        source_labels: Source-label filter supplied by the caller.

    Returns:
        JSON-compatible export envelope with filters and evidence refs.
    """

    return {
        "version": _EVIDENCE_REFS_EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "material_id": str(material_id or "").strip() or None,
            "source_labels": _normalize_filter_values(source_labels),
        },
        "total": len(refs),
        "refs": [_evidence_ref_export_row(ref) for ref in refs],
    }


def _build_evidence_refs_csv(refs: list[EvidenceRefPayload]) -> str:
    """Build a CSV export body with a stable schema and UTF-8 text."""

    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(_EVIDENCE_REFS_EXPORT_CSV_FIELDS))
    writer.writeheader()
    for ref in refs:
        row = _evidence_ref_export_row(ref)
        writer.writerow(
            {
                field: _csv_cell(row.get(field))
                for field in _EVIDENCE_REFS_EXPORT_CSV_FIELDS
            }
        )
    return output.getvalue()


def _download_headers(filename: str) -> dict[str, str]:
    """Return attachment headers for a generated local export."""

    safe_filename = str(filename or "").strip()
    if not safe_filename or safe_filename != Path(safe_filename).name:
        raise HTTPException(status_code=500, detail="invalid evidence refs export filename")
    return {"Content-Disposition": f'attachment; filename="{safe_filename}"'}


def _load_citation_verifications() -> dict[str, CitationVerificationPayload]:
    """Load durable citation verification records and skip malformed rows."""

    payload = _read_json_payload(_evidence_runtime_store_path("citation_verifications.json"))
    raw_records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(raw_records, list):
        return {}

    records: dict[str, CitationVerificationPayload] = {}
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            continue
        try:
            record = CitationVerificationPayload(**raw_record)
        except ValidationError:
            continue
        if record.verification_id.strip():
            records[record.verification_id] = record
    return records


def _write_citation_verifications(records: dict[str, CitationVerificationPayload]) -> None:
    """Persist citation verification records for writing/review sidebars."""

    payload = {
        "version": _CITATION_VERIFICATIONS_VERSION,
        "records": [
            record.model_dump(mode="json")
            for record in sorted(records.values(), key=lambda item: (item.created_at, item.verification_id))
        ],
    }
    _write_json_payload(_evidence_runtime_store_path("citation_verifications.json"), payload)


def _refresh_citation_verifications_store() -> dict[str, CitationVerificationPayload]:
    """Merge durable citation verification records into the process cache."""

    _citation_verifications_store.update(_load_citation_verifications())
    return _citation_verifications_store


# =========================================================================
# A4: Independent evidence_refs API
# =========================================================================

@router.get("/api/evidence_refs", response_model=EvidenceRefsResponse)
async def get_evidence_refs(
    project_id: str = Query(None, description="Filter by project"),
    material_id: str = Query(None, description="Filter by material"),
    source_labels: List[str] = Query(None, description="Filter by source labels"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> EvidenceRefsResponse:
    """Get evidence references with optional source_labels filtering.

    Supports filtering by project_id, material_id, and source_labels.
    """
    refs = _select_evidence_refs(
        material_id=material_id,
        source_labels=source_labels,
    )

    # Pagination
    total = len(refs)
    start = (page - 1) * page_size
    end = start + page_size
    page_refs = refs[start:end]

    return EvidenceRefsResponse(
        refs=page_refs,
        total=total,
        filtered_by_labels=source_labels or [],
    )


@router.get("/api/evidence_refs/export")
async def export_evidence_refs(
    material_id: Optional[str] = Query(None, description="Filter by material"),
    source_labels: List[str] = Query(None, description="Filter by source labels"),
    export_format: Literal["json", "csv"] = Query("json", alias="format"),
) -> Response:
    """Export evidence references as a local JSON or CSV attachment.

    Args:
        material_id: Optional material identifier to match exactly.
        source_labels: Optional source labels; a ref matches any supplied label.
        export_format: Either ``json`` or ``csv``.

    Returns:
        Downloadable response preserving source labels and PDF anchor fields.
    """

    refs = _select_evidence_refs(
        material_id=material_id,
        source_labels=source_labels,
    )
    if export_format == "csv":
        return Response(
            content=_build_evidence_refs_csv(refs),
            media_type="text/csv",
            headers=_download_headers("evidence_refs_export.csv"),
        )

    payload = _build_evidence_refs_export_payload(
        refs=refs,
        material_id=material_id,
        source_labels=source_labels,
    )
    return Response(
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        media_type="application/json",
        headers=_download_headers("evidence_refs_export.json"),
    )


class CreateEvidenceRefRequest(PdfAnchorFields):
    """Request to create evidence reference."""
    chunk_id: str
    material_id: str
    text: str
    compressed_text: str = ""
    quote: str = ""
    label: str = ""
    score: Optional[float] = None
    page: Optional[int] = None
    source: Optional[str] = None
    source_label: Optional[str] = None
    source_labels: List[str] = Field(default_factory=list)


@router.post("/api/evidence_refs", response_model=EvidenceRefPayload)
async def create_evidence_ref(request: CreateEvidenceRefRequest) -> EvidenceRefPayload:
    """Create a new evidence reference with optional bbox."""
    ref_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    ref = EvidenceRefPayload(
        ref_id=ref_id,
        chunk_id=request.chunk_id,
        material_id=request.material_id,
        text=request.text,
        compressed_text=request.compressed_text,
        quote=request.quote,
        label=request.label,
        score=request.score,
        page=request.page,
        source=request.source,
        source_label=request.source_label,
        source_labels=request.source_labels,
        bbox=request.bbox,
        bbox_unit=request.bbox_unit,
        created_at=now,
        updated_at=now,
    )

    _refresh_evidence_refs_store()
    _evidence_refs_store[ref_id] = ref
    _write_evidence_refs(_evidence_refs_store)
    return ref


# =========================================================================
# A5: Source labels CRUD
# =========================================================================

@router.get("/api/source_labels", response_model=List[SourceLabelPayload])
async def list_source_labels() -> List[SourceLabelPayload]:
    """List all source labels."""
    return list(_refresh_source_labels_store().values())


@router.post("/api/source_labels", response_model=SourceLabelPayload)
async def create_source_label(request: CreateSourceLabelRequest) -> SourceLabelPayload:
    """Create a new source label."""
    if not request.name.strip():
        raise HTTPException(status_code=422, detail="source label name must be non-empty")
    label_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    label = SourceLabelPayload(
        label_id=label_id,
        name=request.name.strip(),
        description=request.description,
        color=request.color,
        created_at=now,
        updated_at=now,
    )

    _refresh_source_labels_store()
    _source_labels_store[label_id] = label
    _write_source_labels(_source_labels_store)
    return label


@router.get("/api/source_labels/{label_id}", response_model=SourceLabelPayload)
async def get_source_label(label_id: str) -> SourceLabelPayload:
    """Get a source label by ID."""
    label = _refresh_source_labels_store().get(label_id)
    if not label:
        raise HTTPException(status_code=404, detail=f"Source label not found: {label_id}")
    return label


@router.put("/api/source_labels/{label_id}", response_model=SourceLabelPayload)
async def update_source_label(
    label_id: str,
    request: UpdateSourceLabelRequest,
) -> SourceLabelPayload:
    """Update a source label."""
    label = _refresh_source_labels_store().get(label_id)
    if not label:
        raise HTTPException(status_code=404, detail=f"Source label not found: {label_id}")
    if request.name is not None and not request.name.strip():
        raise HTTPException(status_code=422, detail="source label name must be non-empty")

    now = datetime.now(timezone.utc).isoformat()

    updated = SourceLabelPayload(
        label_id=label.label_id,
        name=request.name.strip() if request.name is not None else label.name,
        description=request.description if request.description is not None else label.description,
        color=request.color if request.color is not None else label.color,
        created_at=label.created_at,
        updated_at=now,
    )

    _source_labels_store[label_id] = updated
    _write_source_labels(_source_labels_store)
    return updated


@router.delete("/api/source_labels/{label_id}")
async def delete_source_label(label_id: str) -> dict[str, str]:
    """Delete a source label."""
    _refresh_source_labels_store()
    if label_id not in _source_labels_store:
        raise HTTPException(status_code=404, detail=f"Source label not found: {label_id}")

    del _source_labels_store[label_id]
    _write_source_labels(_source_labels_store)
    return {"message": f"Source label {label_id} deleted"}


# =========================================================================
# A7: Chunk locator with bbox
# =========================================================================

def _chunk_locator_payload_from_store(project_id: str, chunk_id: str) -> ChunkLocatorPayload:
    """Resolve one chunk locator from the project chunk store.

    Args:
        project_id: Non-empty project identifier owning the chunk store.
        chunk_id: Non-empty chunk identifier to locate.

    Returns:
        Public locator payload with optional page and bbox metadata.

    Raises:
        HTTPException: 404 when the chunk is absent from the project store.
    """
    normalized_project_id = str(project_id or "").strip()
    normalized_chunk_id = str(chunk_id or "").strip()
    if not normalized_project_id:
        raise HTTPException(status_code=422, detail="project_id must be a non-empty string")
    if not normalized_chunk_id:
        raise HTTPException(status_code=422, detail="chunk_id must be a non-empty string")

    chunk_store = _resources_router._load_chunk_store(normalized_project_id)  # type: ignore[attr-defined]
    locator = find_chunk_locator(chunk_store, normalized_chunk_id)
    if locator is None:
        raise HTTPException(
            status_code=404,
            detail=f"chunk_id 未在项目 chunk store 中找到: {normalized_chunk_id}",
        )
    locator = enrich_chunk_locator_with_pdf(normalized_project_id, chunk_store, locator)

    return ChunkLocatorPayload(
        chunk_id=str(locator["chunk_id"]),
        material_id=str(locator["material_id"]),
        page=locator.get("page") if isinstance(locator.get("page"), int) else None,
        chunk_index=locator.get("chunk_index") if isinstance(locator.get("chunk_index"), int) else None,
        bbox=locator.get("bbox") if _is_normalized_ratio_bbox(locator.get("bbox")) else None,
        bbox_unit=PdfBboxUnit.NORMALIZED_RATIO if _is_normalized_ratio_bbox(locator.get("bbox")) else None,
        text_preview=str(locator.get("text_preview") or ""),
    )


def _is_normalized_ratio_bbox(value: Any) -> bool:
    """Return true only for URL-compatible normalized PDF bbox values."""

    bbox = coerce_pdf_bbox(value)
    return bbox is not None and pdf_bbox_matches_unit(bbox, PdfBboxUnit.NORMALIZED_RATIO)


@router.get("/api/chunk_to_page", response_model=ChunkLocatorPayload)
async def chunk_to_page(
    chunk_id: str = Query(..., min_length=1),
    project_id: str = Query(..., min_length=1),
) -> ChunkLocatorPayload:
    """Resolve a chunk id to PDF page and optional bbox metadata."""
    return _chunk_locator_payload_from_store(project_id=project_id, chunk_id=chunk_id)


@router.get("/api/chunks/{chunk_id}/locator", response_model=ChunkLocatorPayload)
async def get_chunk_locator(
    chunk_id: str,
    project_id: Optional[str] = Query(None, min_length=1),
) -> ChunkLocatorPayload:
    """Get chunk locator with bbox information when a project id is provided."""
    if project_id is None:
        return ChunkLocatorPayload(
            chunk_id=chunk_id,
            material_id="",
            page=None,
            chunk_index=None,
            bbox=None,
            text_preview="",
        )
    return _chunk_locator_payload_from_store(project_id=project_id, chunk_id=chunk_id)


# =========================================================================
# D5: Discussion evidence_pack persistence
# =========================================================================

def _discussion_evidence_pack_store_path() -> Path:
    """Return the durable D5 JSON store path under runtime state.

    Returns:
        A pathlib-compatible path with parent directories created by writers.
    """
    return runtime_state_path("discussion", "evidence_packs.json")


def _discussion_evidence_pack_from_raw(raw_pack: Any) -> DiscussionEvidencePackPayload | None:
    """Validate one persisted evidence pack record.

    Args:
        raw_pack: JSON-decoded object expected to match DiscussionEvidencePackPayload.

    Returns:
        Parsed payload, or None when the record is malformed.
    """
    if not isinstance(raw_pack, dict):
        return None
    try:
        return DiscussionEvidencePackPayload(**raw_pack)
    except ValidationError:
        return None


def _load_discussion_evidence_packs() -> dict[str, DiscussionEvidencePackPayload]:
    """Load the durable discussion evidence pack index.

    Returns:
        Mapping keyed by pack_id. Malformed records are skipped so one bad
        artifact cannot break the entire local evidence-pack registry.
    """
    path = _discussion_evidence_pack_store_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    raw_packs = payload.get("packs") if isinstance(payload, dict) else payload
    if not isinstance(raw_packs, list):
        return {}

    loaded: dict[str, DiscussionEvidencePackPayload] = {}
    for raw_pack in raw_packs:
        pack = _discussion_evidence_pack_from_raw(raw_pack)
        if pack is not None and pack.pack_id.strip():
            loaded[pack.pack_id] = pack
    return loaded


def _write_discussion_evidence_packs(
    packs: dict[str, DiscussionEvidencePackPayload],
) -> None:
    """Persist the evidence pack index with tmp+replace semantics.

    Args:
        packs: Mapping keyed by pack_id; values must be serializable Pydantic models.

    Raises:
        HTTPException: 500 when the runtime store cannot be written.
    """
    path = _discussion_evidence_pack_store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _DISCUSSION_EVIDENCE_PACKS_VERSION,
            "packs": [
                pack.model_dump(mode="json")
                for pack in sorted(packs.values(), key=lambda item: (item.created_at, item.pack_id))
            ],
        }
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Evidence pack store write failed: {exc}") from exc


def _refresh_discussion_evidence_pack_store() -> dict[str, DiscussionEvidencePackPayload]:
    """Merge durable D5 packs into the process cache and return the cache."""
    _discussion_packs_store.update(_load_discussion_evidence_packs())
    return _discussion_packs_store


def _bounded_evidence_pack_summary(value: str) -> str:
    """Return a citation-safe summary that cannot dominate model context."""

    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return "Matched evidence chunk"
    if len(text) <= _EVIDENCE_PACK_SUMMARY_CHARS:
        return text
    return f"{text[: _EVIDENCE_PACK_SUMMARY_CHARS - 1].rstrip()}…"


def _citation_anchor_from_ref(ref_id: str, material_id: str, chunk_id: str) -> str:
    """Return a deterministic local citation anchor for evidence traceability."""

    source = f"{material_id}_{chunk_id}_{ref_id}"
    normalized = re.sub(r"[^A-Za-z0-9_\-]+", "_", source).strip("_")
    return normalized[:240] or f"chunk_{uuid.uuid4().hex[:12]}"


def _evidence_pack_ref(project_id: str, query: str, section_id: str | None) -> str:
    """Return a stable opaque pack id for one deterministic lexical build."""

    seed = json.dumps(
        {"project_id": project_id, "query": query, "section_id": section_id or ""},
        ensure_ascii=False,
        sort_keys=True,
    )
    return f"evidence_pack:{uuid.uuid5(uuid.NAMESPACE_URL, seed).hex}"


def _search_ref_to_evidence_ref(project_id: str, ref: Any) -> EvidencePackReferencePayload | None:
    """Project one search ref into the evidence-pack contract.

    Args:
        project_id: Project searched by the evidence-pack builder.
        ref: ``ChunkSearchRefPayload`` returned by the backend search-ref helper.

    Returns:
        A validated evidence-pack ref, or ``None`` when the search ref is not
        safe enough for public MCP output.
    """

    if ref is None:
        return None
    material_id = str(getattr(ref.metadata, "material_id", "") or "").strip()
    chunk_id = str(getattr(ref, "chunk_id", "") or "").strip()
    ref_id = str(getattr(ref, "ref_id", "") or "").strip()
    read_endpoint = str(getattr(ref, "read_endpoint", "") or "").strip()
    if not project_id.strip() or not material_id or not chunk_id or not ref_id or not read_endpoint:
        return None

    summary = _bounded_evidence_pack_summary(str(getattr(ref, "summary", "") or ""))
    page = getattr(ref.metadata, "page", None)
    locator = getattr(ref.metadata, "locator", None)
    if not isinstance(locator, dict):
        locator = None
    source_labels = getattr(ref.metadata, "source_labels", [])
    if not isinstance(source_labels, list):
        source_labels = []
    source_labels = [str(label).strip() for label in source_labels if str(label).strip()][:16]
    figure_candidate = getattr(ref.metadata, "figure_candidate", None)
    figure_candidate = str(figure_candidate).strip()[:260] if figure_candidate is not None else None
    lexical_score = float(getattr(ref, "lexical_score", 0.0) or 0.0)
    rerank_score = getattr(ref, "rerank_score", None)
    evidence_ref = EvidencePackReferencePayload(
        project_id=project_id,
        ref_id=ref_id,
        read_endpoint=read_endpoint,
        chunk_id=chunk_id,
        material_id=material_id,
        page=page,
        locator=locator,
        lexical_score=lexical_score,
        rerank_score=rerank_score,
        citation_anchor=_citation_anchor_from_ref(ref_id, material_id, chunk_id),
        figure_candidate=figure_candidate or None,
        source_labels=source_labels,
        summary=summary,
        suitable_for_body=bool(summary.strip()),
    )
    locator_quality = getattr(ref, "_locator_quality", None)
    if isinstance(locator_quality, dict):
        evidence_ref._locator_quality = dict(locator_quality)
    return evidence_ref


def _resolve_hybrid_retriever_class() -> Any | None:
    """Return the existing hybrid retriever class, or ``None`` if unavailable."""

    try:
        from layers.r_layer_hybrid_retriever import HybridRetrieverWithRerank
    except ImportError:
        return None
    return HybridRetrieverWithRerank


def _resolve_wiki_joint_recall_searcher() -> Any | None:
    """Return a bounded wiki searcher for joint recall diagnostics.

    The searcher returns wiki-ranked bounded refs. Wiki refs remain outside the
    project chunk store, but use the same agent resource reader contract as
    project chunks.
    """

    if not wiki_enabled():
        return None
    index_path = wiki_query_index_path()
    if not index_path.exists():
        return None
    integrity_gate = _wiki_joint_recall_integrity_gate()

    def _search(query: str, limit: int) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        index = WikiQueryIndex(index_path)
        store = WikiPageStore(wiki_generated_root(), create=False)
        try:
            results = index.search(query, limit=limit)
            refs = build_knowledge_refs(results, store, max_summary_chars=300)
            return [ref.to_hit(include_content=False) for ref in refs]
        finally:
            index.close()

    setattr(_search, "_wiki_integrity_gate", integrity_gate)
    return _search


def _wiki_joint_recall_integrity_gate() -> dict[str, Any]:
    """Return a read-only integrity gate for wiki joint recall."""

    if not wiki_enabled():
        return {
            "enabled": False,
            "allowed": False,
            "status": "disabled",
            "reason": "Wiki integration is disabled.",
            "error_class": "wiki_disabled",
        }
    index_path = wiki_query_index_path()
    if not index_path.exists():
        return {
            "enabled": True,
            "allowed": False,
            "status": "missing_index",
            "reason": "Wiki query index is missing; rebuild before using wiki refs in evidence packs.",
            "error_class": "wiki_index_missing",
            "indexed_page_count": 0,
            "source_page_count": None,
            "index_hash": "none",
            "source_manifest_hash": "unknown",
            "indexed_source_manifest_hash": "unknown",
        }
    index = WikiQueryIndex(index_path)
    store = WikiPageStore(wiki_generated_root(), create=False)
    try:
        status = index.get_status(store)
    except Exception as exc:
        return {
            "enabled": True,
            "allowed": False,
            "status": "unreadable_index",
            "reason": f"Wiki query index integrity could not be read: {type(exc).__name__}.",
            "error_class": "wiki_index_unreadable",
            "index_hash": "unknown",
            "source_manifest_hash": "unknown",
            "indexed_source_manifest_hash": "unknown",
        }
    finally:
        index.close()

    allowed = not status.stale and status.integrity_status == "aligned"
    error_class = "" if allowed else f"wiki_{status.integrity_status}"
    reason = (
        "Wiki query index is aligned with generated wiki pages."
        if allowed
        else "Wiki query index is not aligned with generated wiki pages; wiki refs are excluded from this evidence pack."
    )
    return {
        "enabled": True,
        "allowed": allowed,
        "status": status.integrity_status,
        "reason": reason,
        "error_class": error_class[:120],
        "warnings": list(status.warnings),
        "indexed_page_count": status.page_count,
        "source_page_count": status.source_page_count,
        "index_hash": status.index_hash,
        "source_manifest_hash": status.source_manifest_hash,
        "indexed_source_manifest_hash": status.indexed_source_manifest_hash,
        "last_indexed": status.last_indexed,
    }


def _blocked_wiki_joint_recall_result(
    *,
    policy: dict[str, Any],
    project_refs: list[EvidencePackReferencePayload],
    top_k: int,
    gate: dict[str, Any],
) -> tuple[dict[str, Any], list[EvidencePackReferencePayload]]:
    """Return project-only refs plus a blocked wiki integrity diagnostic."""

    return (
        {
            "enabled": bool(gate.get("enabled")),
            "status": "blocked",
            "reason": str(gate.get("reason") or "Wiki integrity gate blocked joint recall."),
            "fusion_method": policy["fusion"],
            "project_weight": float(policy["project_weight"]),
            "wiki_weight": float(policy["wiki_weight"]),
            "project_hit_count": len(project_refs),
            "wiki_hit_count": 0,
            "wiki_share_after_fusion": 0.0,
            "source_counts": {"project": min(len(project_refs), top_k), "wiki": 0},
            "integrity_gate": gate,
            "wiki_summaries": [],
        },
        project_refs[:top_k],
    )


def _project_hits_for_joint_recall(
    evidence_refs: list[EvidencePackReferencePayload],
) -> list[dict[str, Any]]:
    """Convert evidence refs into ranked project hits for fusion diagnostics."""

    hits: list[dict[str, Any]] = []
    for ref in evidence_refs:
        hits.append(
            {
                "doc_id": ref.ref_id,
                "chunk_id": ref.chunk_id,
                "title": ref.material_id,
                "summary": ref.summary,
                "source": "project",
            }
        )
    return hits


def _wiki_hit_to_evidence_ref(project_id: str, hit: dict[str, Any]) -> EvidencePackReferencePayload | None:
    """Project one bounded wiki hit into the evidence-pack ref contract.

    Wiki refs stay as agent-bridge resources and are not copied into project
    chunk stores. The project_id only scopes the evidence-pack build that
    selected the wiki evidence.
    """

    if not project_id.strip() or not isinstance(hit, dict):
        return None
    ref_id = str(hit.get("ref_id") or hit.get("doc_id") or "").strip()
    read_endpoint = str(hit.get("read_endpoint") or "").strip()
    summary = _bounded_evidence_pack_summary(str(hit.get("summary") or ""))
    if not ref_id.startswith("wiki:") or not read_endpoint or not summary.strip():
        return None
    source_path = str(hit.get("page_path") or ref_id.removeprefix("wiki:")).strip()[:240]
    stable_id = ref_id.removeprefix("wiki:").strip() or source_path or ref_id
    hit_chunk_id = str(hit.get("chunk_id") or "").strip()
    chunk_id = hit_chunk_id if hit_chunk_id.startswith("wiki:") else f"wiki:{stable_id}"
    return EvidencePackReferencePayload(
        project_id=project_id,
        source_type="wiki",
        ref_id=ref_id,
        read_endpoint=read_endpoint[:300],
        chunk_id=chunk_id[:260],
        material_id="wiki",
        page=None,
        lexical_score=0.0,
        rerank_score=None,
        citation_anchor=_citation_anchor_from_ref(ref_id, "wiki", stable_id),
        figure_candidate=None,
        source_labels=[],
        summary=summary,
        suitable_for_body=True,
        source_title=str(hit.get("title") or "")[:160] or None,
        source_path=source_path or None,
    )


def _knowledge_hit_to_evidence_ref(
    project_id: str,
    hit: dict[str, Any],
    *,
    source_type: KnowledgeRefSourceType,
) -> EvidencePackReferencePayload | None:
    """Project one knowledge-package hit into the evidence-pack ref contract."""

    if not project_id.strip() or not isinstance(hit, dict):
        return None
    ref_id = str(hit.get("ref_id") or "").strip()
    read_endpoint = str(hit.get("read_endpoint") or "").strip()
    metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
    summary = _bounded_evidence_pack_summary(str(hit.get("summary") or ""))
    expected_read_endpoint = f"/api/agent-bridge/resource/{ref_id}"
    chunk_id = _knowledge_chunk_id_from_ref(ref_id, source_type)
    source_path = str(metadata.get("source_path") or "").strip()[:240]
    content_hash = str(metadata.get("content_hash") or "").strip()
    source_hash = str(metadata.get("source_hash") or "").strip()
    span_start = metadata.get("span_start")
    span_end = metadata.get("span_end")
    if (
        not chunk_id
        or read_endpoint != expected_read_endpoint
        or str(hit.get("kind") or "").strip() != source_type
        or not summary.strip()
        or not source_path
        or not content_hash
        or not source_hash
        or not isinstance(span_start, int)
        or not isinstance(span_end, int)
        or span_end < span_start
    ):
        return None
    lexical_score = float(hit.get("score") or 0.0)
    return EvidencePackReferencePayload(
        project_id=project_id,
        source_type=source_type,
        ref_id=ref_id,
        read_endpoint=read_endpoint[:300],
        chunk_id=f"{source_type}:{chunk_id}"[:260],
        material_id=source_type,
        page=None,
        locator=None,
        lexical_score=max(0.0, lexical_score),
        rerank_score=None,
        citation_anchor=_citation_anchor_from_ref(ref_id, source_type, chunk_id),
        figure_candidate=None,
        source_labels=[],
        summary=summary,
        suitable_for_body=True,
        source_title=str(hit.get("title") or "")[:160] or None,
        source_path=source_path or None,
    )


def _knowledge_chunk_id_from_ref(ref_id: str, source_type: KnowledgeRefSourceType) -> str:
    """Return a stable evidence-pack chunk id suffix from a knowledge ref."""

    if source_type == "product_docs" and ref_id.startswith("product_docs:chunk:"):
        return ref_id.removeprefix("product_docs:chunk:").strip()
    if source_type == "scoring_rules" and ref_id.startswith("scoring_rules:section:"):
        section_id = ref_id.removeprefix("scoring_rules:section:").strip()
        return f"section:{section_id}" if section_id else ""
    if source_type == "academic_english" and ref_id.startswith("academic_english:"):
        if ref_id == "academic_english:habits":
            return "habits:habits"
        parts = ref_id.split(":")
        if len(parts) == 3 and parts[1] in {"habits", "chunk", "phrase"}:
            resource_kind = parts[1].strip()
            item_id = parts[2].strip()
            if resource_kind and item_id:
                return f"{resource_kind}:{item_id}"
    if source_type == "skill_package" and ref_id.startswith("skill_package:"):
        parts = ref_id.split(":")
        if len(parts) == 4 and parts[2] == "chunk":
            package_id = parts[1].strip()
            chunk_id = parts[3].strip()
            if package_id and chunk_id:
                return f"{package_id}:chunk:{chunk_id}"
    if source_type == "source_vault" and ref_id.startswith("source_vault:chunk:"):
        return ref_id.removeprefix("source_vault:chunk:").strip()
    return ""


def _knowledge_summaries(
    hits: list[dict[str, Any]],
    top_k: int,
    *,
    source_type: KnowledgeRefSourceType,
) -> list[dict[str, Any]]:
    """Return bounded knowledge-package provenance summaries for diagnostics."""

    summaries: list[dict[str, Any]] = []
    for hit in hits[: max(0, min(top_k, _EVIDENCE_PACK_MAX_KNOWLEDGE_REFS))]:
        if not isinstance(hit, dict):
            continue
        metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
        summaries.append(
            {
                "ref_id": str(hit.get("ref_id") or ""),
                "read_endpoint": str(hit.get("read_endpoint") or "")[:300],
                "title": str(hit.get("title") or "")[:160],
                "summary": _bounded_evidence_pack_summary(str(hit.get("summary") or "")),
                "source_path": str(metadata.get("source_path") or "")[:240],
                "source_hash": str(metadata.get("source_hash") or "")[:80],
                "content_hash": str(metadata.get("content_hash") or "")[:80],
                "package_content_hash": str(metadata.get("package_content_hash") or "")[:80],
                "span_start": metadata.get("span_start"),
                "span_end": metadata.get("span_end"),
            }
        )
        if source_type == "scoring_rules":
            summaries[-1]["section_id"] = str(metadata.get("section_id") or "")[:120]
        if source_type == "academic_english":
            summaries[-1]["resource_kind"] = str(metadata.get("resource_kind") or "")[:80]
            summaries[-1]["policy_content_hash"] = str(metadata.get("policy_content_hash") or "")[:80]
            summaries[-1]["built_at"] = str(metadata.get("built_at") or "")[:120]
        if source_type == "skill_package":
            summaries[-1]["package_id"] = str(metadata.get("package_id") or "")[:120]
            summaries[-1]["source_role"] = str(metadata.get("source_role") or "")[:80]
        if source_type == "source_vault":
            summaries[-1]["source_id"] = str(metadata.get("source_id") or "")[:120]
            summaries[-1]["chunk_id"] = str(metadata.get("chunk_id") or "")[:160]
            summaries[-1]["chunker_version"] = str(metadata.get("chunker_version") or "")[:80]
    return summaries


def _search_source_vault_knowledge_refs(project_id: str, query: str, top_k: int) -> list[dict[str, Any]]:
    """Return project-scoped Source Vault refs without copying chunk text into evidence packs."""

    if not project_id.strip() or not query.strip() or top_k < 1:
        return []
    hits: list[dict[str, Any]] = []
    for result in SourceVault().search_chunks(query, limit=top_k, project_id=project_id):
        ref_id = build_source_vault_chunk_ref_id(result.chunk_id)
        metadata = build_source_vault_search_metadata(result)
        hits.append(
            {
                "kind": "source_vault",
                "ref_id": ref_id,
                "read_endpoint": build_source_vault_chunk_read_endpoint(result.chunk_id),
                "title": result.title,
                "summary": _source_vault_provenance_summary(result),
                "score": abs(float(result.score)) if result.score is not None else 0.0,
                "metadata": metadata,
            }
        )
    return hits


def _source_vault_provenance_summary(result: Any) -> str:
    """Return a context-safe Source Vault summary that keeps raw chunk text behind resource_read."""

    title = str(getattr(result, "title", "") or "Source Vault source").strip()
    chunk_index = getattr(result, "chunk_index", None)
    page = getattr(result, "page", None)
    section = str(getattr(result, "section", "") or "").strip()
    details: list[str] = []
    if isinstance(chunk_index, int):
        details.append(f"chunk {chunk_index}")
    if isinstance(page, int) and page > 0:
        details.append(f"page {page}")
    if section:
        details.append(f"section {section[:80]}")
    suffix = f" ({', '.join(details)})" if details else ""
    return _bounded_evidence_pack_summary(f"Source Vault bounded ref from {title[:160]}{suffix}.")


def _knowledge_ref_providers() -> tuple[
    tuple[KnowledgeRefSourceType, Callable[[str, str, int], list[dict[str, Any]]]],
    ...,
]:
    """Return evidence-pack knowledge providers in deterministic priority order."""

    return (
        ("product_docs", lambda project_id, query, limit: search_product_docs(query, top_k=limit)),
        ("scoring_rules", lambda project_id, query, limit: search_scoring_rules(query, top_k=limit)),
        ("academic_english", lambda project_id, query, limit: search_academic_english(query, top_k=limit)),
        (
            "skill_package",
            lambda project_id, query, limit: search_skill_package(ACADEMIC_ENGLISH_SKILL_PACKAGE_ID, query, top_k=limit),
        ),
        ("source_vault", _search_source_vault_knowledge_refs),
    )


def _attach_knowledge_refs(
    diagnostics: EvidenceRetrievalDiagnosticsPayload,
    *,
    project_id: str,
    query: str,
    evidence_refs: list[EvidencePackReferencePayload],
    top_k: int,
) -> tuple[EvidenceRetrievalDiagnosticsPayload, list[EvidencePackReferencePayload]]:
    """Attach bounded knowledge-package refs after project/wiki retrieval."""

    if not project_id.strip() or not query.strip() or top_k < 1:
        return diagnostics, evidence_refs
    if not evidence_refs:
        diagnostics.joint_recall["knowledge_refs"] = {
            "enabled": True,
            "status": "skipped",
            "reason": "Project evidence refs are required before knowledge refs are attached.",
            "source_counts": {kind: 0 for kind in _EVIDENCE_PACK_KNOWLEDGE_REF_KINDS},
            "product_docs_summaries": [],
            "scoring_rules_summaries": [],
        }
        return diagnostics, evidence_refs
    remaining = max(0, min(_EVIDENCE_PACK_MAX_KNOWLEDGE_REFS, top_k - len(evidence_refs)))
    if remaining <= 0:
        diagnostics.joint_recall["knowledge_refs"] = {
            "enabled": True,
            "status": "skipped",
            "reason": "Evidence pack top_k was already filled before knowledge refs were considered.",
            "source_counts": {kind: 0 for kind in _EVIDENCE_PACK_KNOWLEDGE_REF_KINDS},
            "product_docs_summaries": [],
            "scoring_rules_summaries": [],
        }
        return diagnostics, evidence_refs

    refs: list[EvidencePackReferencePayload] = []
    seen = {ref.ref_id for ref in evidence_refs}
    source_counts = {kind: 0 for kind in _EVIDENCE_PACK_KNOWLEDGE_REF_KINDS}
    summaries: dict[str, list[dict[str, Any]]] = {f"{kind}_summaries": [] for kind in _EVIDENCE_PACK_KNOWLEDGE_REF_KINDS}
    blocked: list[str] = []
    for source_type, searcher in _knowledge_ref_providers():
        if len(refs) >= remaining:
            break
        provider_limit = 1
        try:
            hits = searcher(project_id, query, provider_limit)
        except Exception as exc:
            blocked.append(source_type)
            diagnostics.notes = [
                *diagnostics.notes,
                f"{source_type} knowledge refs were blocked before entering this evidence pack.",
            ][:12]
            continue
        summaries[f"{source_type}_summaries"] = _knowledge_summaries(hits, top_k, source_type=source_type)
        for hit in hits:
            ref = _knowledge_hit_to_evidence_ref(project_id, hit, source_type=source_type)
            if ref is None or ref.ref_id in seen:
                continue
            refs.append(ref)
            seen.add(ref.ref_id)
            source_counts[source_type] += 1
            if len(refs) >= remaining:
                break

    status = "active" if refs else "blocked" if blocked else "empty"
    diagnostics.joint_recall["knowledge_refs"] = {
        "enabled": True,
        "status": status,
        "reason": (
            "Attached bounded knowledge refs that share agent resource ids with knowledge search."
            if refs
            else f"Knowledge ref providers were blocked: {', '.join(blocked)}."
            if blocked
            else "Knowledge package searches returned no bounded refs for this query."
        ),
        "source_counts": source_counts,
        "blocked_sources": blocked,
        **summaries,
    }
    if refs:
        diagnostics.reasoning_trace = [
            *diagnostics.reasoning_trace,
            "Attached knowledge refs through the same bounded agent resource protocol used by knowledge search.",
        ][:16]
        diagnostics.notes = [
            *diagnostics.notes,
            "knowledge_refs may include non-project bounded refs; raw knowledge content stays behind resource_read.",
        ][:12]
    return diagnostics, [*evidence_refs, *refs]


def _evidence_refs_from_fused_joint_hits(
    *,
    project_id: str,
    fused_hits: list[dict[str, Any]],
    project_refs: list[EvidencePackReferencePayload],
    top_k: int,
) -> list[EvidencePackReferencePayload]:
    """Return project+wiki evidence refs in weighted-RRF order."""

    if top_k < 1:
        raise ValueError("top_k must be positive")
    project_by_ref_id = {ref.ref_id: ref for ref in project_refs}
    output: list[EvidencePackReferencePayload] = []
    seen: set[str] = set()
    for fused in fused_hits:
        if not isinstance(fused, dict):
            continue
        doc_id = str(fused.get("doc_id") or "").strip()
        payload = fused.get("payload") if isinstance(fused.get("payload"), dict) else {}
        ref: EvidencePackReferencePayload | None = None
        if doc_id in project_by_ref_id:
            ref = project_by_ref_id[doc_id]
        elif str(fused.get("dominant_source") or "") == "wiki":
            ref = _wiki_hit_to_evidence_ref(project_id, payload)
        if ref is None or ref.ref_id in seen:
            continue
        ref.joint_score = float(fused.get("joint_score") or 0.0)
        output.append(ref)
        seen.add(ref.ref_id)
        if len(output) >= top_k:
            break
    if len(output) < top_k:
        for ref in project_refs:
            if ref.ref_id in seen:
                continue
            output.append(ref)
            seen.add(ref.ref_id)
            if len(output) >= top_k:
                break
    return output


def _joint_recall_diagnostics(
    *,
    project_id: str,
    query: str,
    project_refs: list[EvidencePackReferencePayload],
    top_k: int,
) -> tuple[dict[str, Any], list[EvidencePackReferencePayload]]:
    """Return wiki+project fusion diagnostics and fused evidence refs."""

    policy = default_joint_recall_policy()
    searcher = _resolve_wiki_joint_recall_searcher()
    if searcher is None:
        gate = _wiki_joint_recall_integrity_gate()
        if gate.get("enabled") and not gate.get("allowed"):
            return _blocked_wiki_joint_recall_result(
                policy=policy,
                project_refs=project_refs,
                top_k=top_k,
                gate=gate,
            )
        return (
            {
                "enabled": False,
                "status": "unavailable",
                "reason": "wiki disabled or query index unavailable",
                "fusion_method": policy["fusion"],
                "project_weight": float(policy["project_weight"]),
                "wiki_weight": float(policy["wiki_weight"]),
                "project_hit_count": len(project_refs),
                "wiki_hit_count": 0,
                "wiki_share_after_fusion": 0.0,
                "source_counts": {"project": min(len(project_refs), top_k), "wiki": 0},
            },
            project_refs[:top_k],
        )
    gate = getattr(searcher, "_wiki_integrity_gate", None)
    if isinstance(gate, dict) and not gate.get("allowed", False):
        return _blocked_wiki_joint_recall_result(
            policy=policy,
            project_refs=project_refs,
            top_k=top_k,
            gate=gate,
        )
    wiki_hits = searcher(query, max(top_k, int(policy.get("per_source_caps", {}).get("wiki", top_k))))
    if not isinstance(wiki_hits, list):
        wiki_hits = []
    fused = weighted_rrf_fuse(
        project_hits=_project_hits_for_joint_recall(project_refs),
        wiki_hits=[hit for hit in wiki_hits if isinstance(hit, dict)],
        top_k=top_k,
        policy=policy,
    )
    source_counts = {
        "project": sum(1 for hit in fused["hits"] if hit.get("dominant_source") == "project"),
        "wiki": sum(1 for hit in fused["hits"] if hit.get("dominant_source") == "wiki"),
    }
    evidence_refs = _evidence_refs_from_fused_joint_hits(
        project_id=project_id,
        fused_hits=fused["hits"],
        project_refs=project_refs,
        top_k=top_k,
    )
    return (
        {
            "enabled": True,
            "status": "active" if wiki_hits else "empty",
            "fusion_method": fused["fusion_method"],
            "project_weight": fused["project_weight"],
            "wiki_weight": fused["wiki_weight"],
            "project_hit_count": fused["project_hit_count"],
            "wiki_hit_count": fused["wiki_hit_count"],
            "wiki_share_after_fusion": fused["wiki_share_after_fusion"],
            "source_counts": source_counts,
            "integrity_gate": gate if isinstance(gate, dict) else {"status": "unchecked"},
            "top_doc_ids": [str(hit.get("doc_id") or "") for hit in fused["hits"][: min(5, top_k)]],
            "wiki_summaries": [
                {
                    "doc_id": str(hit.get("doc_id") or ""),
                    "ref_id": str(hit.get("ref_id") or hit.get("doc_id") or ""),
                    "read_endpoint": str(hit.get("read_endpoint") or "")[:300],
                    "title": str(hit.get("title") or "")[:160],
                    "summary": _bounded_evidence_pack_summary(str(hit.get("summary") or "")),
                    "page_path": str(hit.get("page_path") or "")[:240],
                    "source": str(hit.get("source") or "wiki")[:80],
                    "chunk_id": str(hit.get("chunk_id") or "")[:260],
                    "source_hash": str(hit.get("source_hash") or "")[:80],
                    "content_hash": str(hit.get("content_hash") or "")[:80],
                    "span_start": hit.get("span_start"),
                    "span_end": hit.get("span_end"),
                }
                for hit in wiki_hits[: min(3, top_k)]
                if isinstance(hit, dict)
            ],
        },
        evidence_refs,
    )


def _attach_joint_recall_diagnostics(
    diagnostics: EvidenceRetrievalDiagnosticsPayload,
    *,
    project_id: str,
    query: str,
    evidence_refs: list[EvidencePackReferencePayload],
    top_k: int,
) -> tuple[EvidenceRetrievalDiagnosticsPayload, list[EvidencePackReferencePayload]]:
    """Attach wiki+project recall diagnostics to an existing provenance payload."""

    joint, fused_refs = _joint_recall_diagnostics(
        project_id=project_id,
        query=query,
        project_refs=evidence_refs,
        top_k=top_k,
    )
    diagnostics.joint_recall = joint
    joint_status = str(joint.get("status") or "")
    if joint.get("enabled") and joint_status == "active":
        diagnostics.project_weight = float(joint.get("project_weight", diagnostics.project_weight))
        diagnostics.wiki_weight = float(joint.get("wiki_weight", diagnostics.wiki_weight))
        diagnostics.reasoning_trace = [
            *diagnostics.reasoning_trace,
            "Computed wiki+project weighted RRF and projected bounded wiki refs without adding wiki pages to project chunks.",
        ][:16]
        diagnostics.notes = [
            *diagnostics.notes,
            "joint_recall evidence_refs may include source_type=wiki bounded refs alongside project chunk refs.",
        ][:12]
    elif joint_status == "blocked":
        diagnostics.reasoning_trace = [
            *diagnostics.reasoning_trace,
            "Skipped wiki joint recall because the wiki integrity gate blocked stale or unproven wiki refs.",
        ][:16]
        diagnostics.notes = [
            *diagnostics.notes,
            "wiki_integrity_gate blocked wiki refs from entering this evidence pack.",
        ][:12]
    return diagnostics, fused_refs


async def _build_hybrid_evidence_refs(
    *,
    project_id: str,
    query: str,
    top_k: int,
    all_chunks: list[dict[str, Any]],
) -> tuple[list[EvidencePackReferencePayload], EvidenceRetrievalDiagnosticsPayload] | None:
    """Try the existing hybrid retriever and return refs plus diagnostics.

    Args:
        project_id: Project owning the chunk store.
        query: Section/query text.
        top_k: Maximum evidence refs requested.
        all_chunks: Flattened project chunks already loaded by the caller.

    Returns:
        ``None`` when hybrid retrieval is unavailable or yields no usable refs;
        otherwise MCP-safe refs and an explicit diagnostic payload.
    """

    if not project_id.strip() or not query.strip() or top_k < 1 or not all_chunks:
        return None
    retriever_class = _resolve_hybrid_retriever_class()
    if retriever_class is None:
        return None

    retriever = retriever_class(use_reranker=None)
    try:
        hits = await retriever.search(
            {"chunks": all_chunks, "claim_index": all_chunks},
            query=query,
            top_k=top_k,
            focus_keywords=None,
        )
    except Exception:
        return None
    if not hits:
        return None

    evidence_refs: list[EvidencePackReferencePayload] = []
    dense_used = False
    rerank_active = False
    rerank_fallback = False
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        labels = [str(label).lower() for label in hit.get("source_labels", []) if isinstance(label, str)]
        dense_used = dense_used or "dense" in labels
        rerank_active = rerank_active or "rerank" in labels or hit.get("rerank_score") is not None
        rerank_fallback = rerank_fallback or "rerank_fallback" in labels
        score = float(hit.get("hybrid_score") or hit.get("rerank_score") or 0.0)
        search_ref = _chunk_to_search_ref(project_id, score, hit)
        evidence_ref = _search_ref_to_evidence_ref(project_id, search_ref)
        if evidence_ref is None:
            continue
        if hit.get("rerank_score") is not None:
            evidence_ref.rerank_score = float(hit.get("rerank_score") or 0.0)
        evidence_refs.append(evidence_ref)
        if len(evidence_refs) >= top_k:
            break
    if not evidence_refs or not (dense_used or rerank_active):
        return None

    retrieval_method: Literal["hybrid", "hybrid_rerank"] = "hybrid_rerank" if rerank_active else "hybrid"
    embedding_status: Literal["active", "skipped", "unavailable"] = "active" if dense_used else "skipped"
    rerank_status: Literal["active", "skipped", "unavailable"] = (
        "active" if rerank_active and not rerank_fallback else "skipped"
    )
    diagnostics = EvidenceRetrievalDiagnosticsPayload(
        retrieval_method=retrieval_method,
        embedding_status=embedding_status,
        rerank_status=rerank_status,
        fallback_reason="" if rerank_status == "active" else "Hybrid retrieval ran without an active rerank result.",
        project_weight=1.0,
        wiki_weight=0.0,
        reasoning_trace=[
            "Loaded persisted project chunk store.",
            "Ran existing ContextAwareRetriever/HybridRetrieverWithRerank over project chunks.",
            "Projected hybrid hits into MCP-safe evidence refs without raw content.",
            "Recorded dense/rerank provenance from retriever source labels and score fields.",
        ],
        notes=[
            "embedding_status=active requires chunk embeddings and query embedding success.",
            "rerank_status=active requires a returned rerank_score or rerank provenance label.",
        ],
    )
    return evidence_refs, diagnostics


def _lexical_evidence_diagnostics() -> EvidenceRetrievalDiagnosticsPayload:
    """Return the explicit lexical fallback diagnostics used by evidence packs."""

    return EvidenceRetrievalDiagnosticsPayload(
        retrieval_method="lexical",
        embedding_status="unavailable",
        rerank_status="unavailable",
        fallback_reason=(
            "Evidence-pack builder used the MCP-safe lexical fallback; "
            "dense embedding and local/API rerank were not invoked for this result."
        ),
        project_weight=1.0,
        wiki_weight=0.0,
        reasoning_trace=[
            "Loaded persisted project chunk store.",
            "Applied lexical token/sub-string scoring to existing chunks.",
            "Projected hits into MCP-safe evidence refs without raw content.",
            "Marked embedding/rerank unavailable because hybrid evidence-pack retrieval did not produce usable refs.",
        ],
        notes=[
            "Use retrieval_method/rerank_status to audit whether embedding or rerank participated.",
            "Hybrid/rerank evidence-pack retrieval runs only when existing retriever returns usable hits.",
        ],
    )


def _evidence_pack_qrels_attempt(qrels_status: RetrievalQrelsStatusPayload) -> ToolAttempt:
    """Return a bounded qrels quality-gate attempt for the outcome envelope."""

    if qrels_status.status == "canonical":
        return ToolAttempt(
            stage="qrels_quality_gate",
            status="success",
            reason="Canonical qrels are available for retrieval-quality evaluation.",
            metadata={
                "status": qrels_status.status,
                "canonical_qrels_count": qrels_status.canonical_qrels_count,
                "quality_claim": qrels_status.quality_claim,
            },
        )
    if qrels_status.status in {"candidate", "reviewed"}:
        return ToolAttempt(
            stage="qrels_quality_gate",
            status="blocked",
            reason="Retrieval quality claims require canonical qrels.",
            error_class="qrels_review_needed",
            recommendation="Review or promote qrels before making semantic retrieval-quality claims.",
            metadata={
                "status": qrels_status.status,
                "candidate_qrels_count": qrels_status.candidate_qrels_count,
                "reviewed_qrels_count": qrels_status.reviewed_qrels_count,
                "quality_claim": qrels_status.quality_claim,
            },
        )
    return ToolAttempt(
        stage="qrels_quality_gate",
        status="skipped",
        reason="No qrels were found; retrieval method is provenance, not semantic quality proof.",
        error_class="qrels_missing",
        metadata={
            "status": qrels_status.status,
            "quality_claim": qrels_status.quality_claim,
        },
    )


def _evidence_pack_locator_attempt(diagnostics: EvidenceRetrievalDiagnosticsPayload) -> ToolAttempt:
    """Return a locator-coverage attempt for workflow and integrity gates."""

    coverage = diagnostics.locator_coverage
    status = "success" if coverage.risk_level == "none" else "blocked" if coverage.risk_level == "block" else "degraded"
    reason_by_state: dict[str, str] = {
        "no_refs": "No project refs were returned for source locator coverage.",
        "missing": "Returned project refs are missing material/chunk locators.",
        "material_only": "Returned project refs identify chunks but lack source pages.",
        "page_located": "Returned project refs can jump to pages but not exact layout boxes.",
        "layout_partial": "Some returned project refs include page+bbox locators.",
        "layout_complete": "Every returned project ref includes material, page, and bbox locators.",
    }
    recommendation = ""
    if coverage.risk_level == "block":
        recommendation = "Run or repair material processing before treating these refs as fully auditable evidence."
    elif coverage.risk_level == "warn":
        recommendation = "Use page locators for review and add bbox-capable extraction before layout-sensitive claims."
    return ToolAttempt(
        stage="locator_coverage",
        status=status,
        reason=reason_by_state.get(coverage.coverage_state, "Locator coverage was computed."),
        error_class="" if coverage.risk_level == "none" else f"locator_coverage_{coverage.coverage_state}",
        recommendation=recommendation,
        metadata=coverage.model_dump(mode="json"),
    )


def _evidence_pack_wiki_integrity_attempt(diagnostics: EvidenceRetrievalDiagnosticsPayload) -> ToolAttempt:
    """Return a wiki integrity gate attempt for joint recall provenance."""

    joint = diagnostics.joint_recall if isinstance(diagnostics.joint_recall, dict) else {}
    gate = joint.get("integrity_gate") if isinstance(joint.get("integrity_gate"), dict) else {}
    if not gate:
        return ToolAttempt(
            stage="wiki_integrity_gate",
            status="skipped",
            reason="Wiki integrity gate was not evaluated for this evidence pack.",
            error_class="wiki_gate_unavailable",
            metadata={"joint_recall_status": str(joint.get("status") or "disabled")},
        )
    gate_status = str(gate.get("status") or "unknown")
    if gate.get("allowed") is True and gate_status == "aligned":
        return ToolAttempt(
            stage="wiki_integrity_gate",
            status="success",
            reason="Wiki query index is aligned with generated wiki pages.",
            metadata={
                "status": gate_status,
                "indexed_page_count": gate.get("indexed_page_count"),
                "source_page_count": gate.get("source_page_count"),
                "index_hash": gate.get("index_hash"),
                "source_manifest_hash": gate.get("source_manifest_hash"),
            },
        )
    if gate.get("enabled") is False:
        return ToolAttempt(
            stage="wiki_integrity_gate",
            status="skipped",
            reason=str(gate.get("reason") or "Wiki integration is disabled."),
            error_class=str(gate.get("error_class") or "wiki_disabled")[:120],
            metadata={"status": gate_status},
        )
    return ToolAttempt(
        stage="wiki_integrity_gate",
        status="blocked",
        reason=str(gate.get("reason") or "Wiki query index integrity blocked wiki refs.")[:240],
        error_class=str(gate.get("error_class") or f"wiki_{gate_status}")[:120],
        recommendation="Rebuild the wiki query index before using wiki refs in evidence-pack context.",
        metadata={
            "status": gate_status,
            "warnings": list(gate.get("warnings") or [])[:8],
            "indexed_page_count": gate.get("indexed_page_count"),
            "source_page_count": gate.get("source_page_count"),
            "index_hash": gate.get("index_hash"),
            "source_manifest_hash": gate.get("source_manifest_hash"),
            "indexed_source_manifest_hash": gate.get("indexed_source_manifest_hash"),
        },
    )


def _evidence_pack_knowledge_refs_attempt(diagnostics: EvidenceRetrievalDiagnosticsPayload) -> ToolAttempt:
    """Return a bounded knowledge-ref attempt for non-project context sources."""

    joint = diagnostics.joint_recall if isinstance(diagnostics.joint_recall, dict) else {}
    knowledge_refs = joint.get("knowledge_refs") if isinstance(joint.get("knowledge_refs"), dict) else {}
    if not knowledge_refs:
        return ToolAttempt(
            stage="knowledge_refs",
            status="skipped",
            reason="No non-project knowledge refs were evaluated for this evidence pack.",
            metadata={"enabled": False, "source_counts": {}},
        )
    status = str(knowledge_refs.get("status") or "skipped")
    source_counts = knowledge_refs.get("source_counts") if isinstance(knowledge_refs.get("source_counts"), dict) else {}
    if status == "active":
        return ToolAttempt(
            stage="knowledge_refs",
            status="success",
            reason="Non-project knowledge refs contributed bounded agent resources.",
            metadata={"enabled": True, "status": status, "source_counts": dict(source_counts)},
        )
    if status == "blocked":
        return ToolAttempt(
            stage="knowledge_refs",
            status="blocked",
            reason=str(knowledge_refs.get("reason") or "Knowledge refs were blocked.")[:240],
            error_class=str(knowledge_refs.get("error_class") or "knowledge_refs_blocked")[:120],
            recommendation="Repair the knowledge package manifest/search path before loading these refs into model context.",
            metadata={"enabled": True, "status": status, "source_counts": dict(source_counts)},
        )
    return ToolAttempt(
        stage="knowledge_refs",
        status="skipped",
        reason=str(knowledge_refs.get("reason") or "No non-project knowledge refs contributed.")[:240],
        metadata={"enabled": True, "status": status, "source_counts": dict(source_counts)},
    )


def _evidence_pack_next_action(
    *,
    project_id: str,
    evidence_refs: list[EvidencePackReferencePayload],
    qrels_status: RetrievalQrelsStatusPayload,
) -> ToolNextAction:
    """Choose the safest follow-up that does not mutate project state implicitly."""

    if evidence_refs:
        first_ref = evidence_refs[0]
        return ToolNextAction(
            kind="read_resource",
            message="Read the top evidence resource before using the pack in prose.",
            endpoint=first_ref.read_endpoint,
            args={"project_id": project_id, "ref_id": first_ref.ref_id},
        )
    if qrels_status.status in {"candidate", "reviewed"}:
        return ToolNextAction(
            kind="review_qrels",
            message="Review or promote qrels before claiming semantic retrieval quality.",
            args={"project_id": project_id, "qrels_status": qrels_status.status},
        )
    return ToolNextAction(
        kind="scan_folder",
        message="No evidence refs were found; scan the project source folder after adding PDFs/full text.",
        tool_name="literature.project_scan_folder",
        args={"project_id": project_id},
    )


def _evidence_pack_outcome(
    *,
    project_id: str,
    all_chunks: list[dict[str, Any]],
    evidence_refs: list[EvidencePackReferencePayload],
    diagnostics: EvidenceRetrievalDiagnosticsPayload,
    positive_hit_count: int,
    qrels_status: RetrievalQrelsStatusPayload,
) -> ToolOutcome:
    """Build a ScanSci-style outcome envelope without changing legacy fields."""

    attempts: list[ToolAttempt] = [
        ToolAttempt(
            stage="chunk_load",
            status="success" if all_chunks else "skipped",
            reason=(
                "Loaded indexed project chunks."
                if all_chunks
                else "No indexed project chunks were found for this project."
            ),
            error_class="" if all_chunks else "ingest_needed",
            recommendation="" if all_chunks else "Add PDFs/full text and run literature.project_scan_folder.",
            metadata={"chunk_count": len(all_chunks)},
        )
    ]
    if all_chunks:
        attempts.append(
            ToolAttempt(
                stage="retrieval",
                status="success" if evidence_refs else "skipped",
                reason=(
                    f"Used {diagnostics.retrieval_method} retrieval and returned evidence refs."
                    if evidence_refs
                    else "Indexed chunks existed, but no positive lexical or hybrid hits were returned."
                ),
                error_class="" if evidence_refs else "retrieval_empty",
                metadata={
                    "retrieval_method": diagnostics.retrieval_method,
                    "positive_hit_count": positive_hit_count,
                    "returned_ref_count": len(evidence_refs),
                },
            )
        )
    attempts.append(
        ToolAttempt(
            stage="rerank",
            status="success" if diagnostics.rerank_status == "active" else "skipped",
            reason=(
                "Rerank participated in the evidence-pack result."
                if diagnostics.rerank_status == "active"
                else "Rerank did not participate in this evidence-pack result."
            ),
            error_class="" if diagnostics.rerank_status == "active" else "rerank_unavailable",
            recommendation=(
                ""
                if diagnostics.rerank_status == "active"
                else "Configure rerank or embeddings only if semantic reranking is required."
            ),
            metadata={
                "rerank_status": diagnostics.rerank_status,
                "embedding_status": diagnostics.embedding_status,
            },
        )
    )
    joint_status = str(diagnostics.joint_recall.get("status") or "disabled")
    attempts.append(
        ToolAttempt(
            stage="joint_recall",
            status="success" if joint_status == "active" else "blocked" if joint_status == "blocked" else "skipped",
            reason=(
                "Wiki+project joint recall contributed bounded refs."
                if joint_status == "active"
                else "Wiki+project joint recall was blocked by the wiki integrity gate."
                if joint_status == "blocked"
                else "Wiki+project joint recall did not contribute refs."
            ),
            error_class="wiki_integrity_blocked" if joint_status == "blocked" else "",
            metadata={
                "enabled": bool(diagnostics.joint_recall.get("enabled")),
                "status": joint_status,
                "project_weight": diagnostics.project_weight,
                "wiki_weight": diagnostics.wiki_weight,
            },
        )
    )
    attempts.append(_evidence_pack_wiki_integrity_attempt(diagnostics))
    attempts.append(_evidence_pack_knowledge_refs_attempt(diagnostics))
    attempts.append(_evidence_pack_locator_attempt(diagnostics))
    attempts.append(_evidence_pack_qrels_attempt(qrels_status))

    if evidence_refs:
        status = "success" if diagnostics.rerank_status == "active" else "degraded"
        reason = (
            "Evidence refs returned with active rerank provenance."
            if diagnostics.rerank_status == "active"
            else "Evidence refs returned without active rerank provenance."
        )
    elif all_chunks:
        status = "empty"
        reason = "Project chunks were indexed, but this query returned no evidence refs."
    else:
        status = "empty"
        reason = "No indexed project chunks were available for evidence-pack retrieval."

    return ToolOutcome(
        status=status,
        quality="refs_only" if evidence_refs else "none",
        reason=reason,
        next_action=_evidence_pack_next_action(
            project_id=project_id,
            evidence_refs=evidence_refs,
            qrels_status=qrels_status,
        ),
        attempts=attempts,
    )


@router.post("/api/evidence-pack/build", response_model=EvidencePackBuildResponse)
async def build_evidence_pack(request: EvidencePackBuildRequest) -> EvidencePackBuildResponse:
    """Build a query-scoped evidence pack from existing project chunks.

    The current production-safe implementation is explicit lexical fallback:
    it reuses the same white-listed search-ref projection as MCP retrieval and
    reports rerank as unavailable rather than implying hybrid retrieval ran.
    """

    project_id = request.project_id.strip()
    query = request.query.strip()
    section_id = request.section_id.strip() if isinstance(request.section_id, str) and request.section_id.strip() else None
    if not project_id:
        raise HTTPException(status_code=422, detail="project_id must be non-empty")
    if not query:
        raise HTTPException(status_code=422, detail="query must be non-empty")

    chunk_store = _resources_router._load_chunk_store(project_id)
    all_chunks = _flatten_chunk_store_for_search_refs(chunk_store)
    evidence_refs: list[EvidencePackReferencePayload] = []
    positive_hit_count = 0
    retrieval_method: Literal["lexical", "hybrid", "hybrid_rerank"] = "lexical"
    rerank_status: Literal["active", "skipped", "unavailable"] = "unavailable"
    diagnostics = _lexical_evidence_diagnostics()
    if all_chunks:
        hybrid_result = await _build_hybrid_evidence_refs(
            project_id=project_id,
            query=query,
            top_k=request.top_k,
            all_chunks=all_chunks,
        )
        if hybrid_result is not None:
            evidence_refs, diagnostics = hybrid_result
            retrieval_method = diagnostics.retrieval_method
            rerank_status = diagnostics.rerank_status
            positive_hit_count = len(evidence_refs)
        else:
            scored = _resources_router._score_chunks_for_query(all_chunks, query)
            positive_hit_count = len([score for score, _chunk in scored if score > 0])
            for score, chunk in _resources_router._select_diverse_top_chunks(scored, top_k=request.top_k):
                search_ref = _chunk_to_search_ref(project_id, score, chunk)
                evidence_ref = _search_ref_to_evidence_ref(project_id, search_ref)
                if evidence_ref is not None:
                    evidence_refs.append(evidence_ref)

    diagnostics, evidence_refs = _attach_joint_recall_diagnostics(
        diagnostics,
        project_id=project_id,
        query=query,
        evidence_refs=evidence_refs,
        top_k=request.top_k,
    )
    diagnostics, evidence_refs = _attach_knowledge_refs(
        diagnostics,
        project_id=project_id,
        query=query,
        evidence_refs=evidence_refs,
        top_k=request.top_k,
    )
    diagnostics.locator_coverage = build_locator_coverage(evidence_refs)
    qrels_status = _project_qrels_status(project_id)
    diagnostics.qrels_status = qrels_status
    outcome = _evidence_pack_outcome(
        project_id=project_id,
        all_chunks=all_chunks,
        evidence_refs=evidence_refs,
        diagnostics=diagnostics,
        positive_hit_count=positive_hit_count,
        qrels_status=qrels_status,
    )

    return EvidencePackBuildResponse(
        evidence_pack_ref=_evidence_pack_ref(project_id, query, section_id),
        project_id=project_id,
        query=query,
        section_id=section_id,
        retrieval_method=retrieval_method,
        rerank_status=rerank_status,
        total=len(evidence_refs),
        truncated=positive_hit_count > len(evidence_refs),
        retrieval_diagnostics=diagnostics,
        outcome=outcome,
        evidence_refs=evidence_refs,
    )


class SaveEvidencePackRequest(BaseModel):
    """Request to save discussion evidence pack.

    Args:
        project_id: Non-empty project identifier for the discussion.
        query: Non-empty discussion prompt or research question.
        snippets: JSON-serializable evidence snippets captured for the run.
        source_labels: Optional source labels attached to the pack.
    """

    project_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=4096)
    snippets: List[dict[str, Any]] = Field(default_factory=list)
    source_labels: List[str] = Field(default_factory=list)


@router.post("/api/discussions/{discussion_id}/evidence_pack", response_model=DiscussionEvidencePackPayload)
async def save_discussion_evidence_pack(
    discussion_id: str,
    request: SaveEvidencePackRequest,
) -> DiscussionEvidencePackPayload:
    """Save evidence pack for a discussion session."""
    normalized_discussion_id = discussion_id.strip()
    if not normalized_discussion_id:
        raise HTTPException(status_code=422, detail="discussion_id must be non-empty")

    pack_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    pack = DiscussionEvidencePackPayload(
        pack_id=pack_id,
        discussion_id=normalized_discussion_id,
        project_id=request.project_id.strip(),
        query=request.query.strip(),
        created_at=now,
        snippets=request.snippets,
        source_labels=request.source_labels,
    )

    _refresh_discussion_evidence_pack_store()
    _discussion_packs_store[pack_id] = pack
    _write_discussion_evidence_packs(_discussion_packs_store)
    return pack


@router.get("/api/discussions/{discussion_id}/evidence_pack", response_model=DiscussionEvidencePackPayload)
async def get_discussion_evidence_pack(discussion_id: str) -> DiscussionEvidencePackPayload:
    """Get evidence pack for a discussion session."""
    normalized_discussion_id = discussion_id.strip()
    if not normalized_discussion_id:
        raise HTTPException(status_code=422, detail="discussion_id must be non-empty")

    matching = [
        pack
        for pack in _refresh_discussion_evidence_pack_store().values()
        if pack.discussion_id == normalized_discussion_id
    ]
    if matching:
        return max(matching, key=lambda pack: (pack.created_at, pack.pack_id))

    raise HTTPException(status_code=404, detail=f"Evidence pack not found for discussion: {normalized_discussion_id}")


# =========================================================================
# D8: Citation overlap detector
# =========================================================================

class DetectOverlapAnchor(BaseModel):
    """Citation anchor candidate supplied by the caller for D8 overlap checks."""

    anchor_id: str = Field(min_length=1, max_length=128)
    material_id: str = Field(default="", max_length=128)
    chunk_id: str = Field(default="", max_length=128)
    text: str = Field(default="", max_length=4096)


class DetectOverlapRequest(BaseModel):
    """Request to detect citation overlap."""

    project_id: str
    draft_id: Optional[str] = None
    threshold: float = Field(0.7, ge=0.0, le=1.0, description="Overlap threshold")
    anchors: List[DetectOverlapAnchor] = Field(default_factory=list)


_OVERLAP_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


def _citation_overlap_tokens(value: str) -> set[str]:
    """Return normalized tokens used for bounded citation text overlap."""
    if not isinstance(value, str):
        return set()
    return {token.lower() for token in _OVERLAP_TOKEN_RE.findall(value) if token.strip()}


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    """Return set Jaccard similarity; empty pairs are not evidence overlap."""
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _anchor_overlap_score(left: DetectOverlapAnchor, right: DetectOverlapAnchor) -> float:
    """Score exact chunk reuse first, then text-token Jaccard similarity."""
    left_chunk = left.chunk_id.strip()
    right_chunk = right.chunk_id.strip()
    if left_chunk and left_chunk == right_chunk:
        left_material = left.material_id.strip()
        right_material = right.material_id.strip()
        if not left_material or not right_material or left_material == right_material:
            return 1.0
    return _jaccard_similarity(
        _citation_overlap_tokens(left.text),
        _citation_overlap_tokens(right.text),
    )


def _overlap_recommendation(score: float, overlapping_count: int) -> str:
    """Return a deterministic reviewer hint for overlapping citation anchors."""
    if score >= 1.0:
        return "多个 citation anchor 指向同一证据块，请确认是否需要合并引用或补充独立证据。"
    if overlapping_count > 1:
        return "多个 citation anchor 与其他引用高度相似，请检查证据是否过度集中。"
    return "该 citation anchor 与另一引用高度相似，请检查是否需要补充独立证据。"


@router.post("/api/citations/detect_overlap", response_model=List[CitationOverlapPayload])
async def detect_citation_overlap(request: DetectOverlapRequest) -> List[CitationOverlapPayload]:
    """Detect overlapping citations in a project or draft.

    Identifies citation anchors that reference the same or highly similar chunks.
    """
    if not request.project_id.strip():
        raise HTTPException(status_code=422, detail="project_id must be non-empty")
    if len(request.anchors) < 2:
        return []

    overlap_by_anchor: dict[str, dict[str, Any]] = {}
    for index, left in enumerate(request.anchors):
        for right in request.anchors[index + 1:]:
            if left.anchor_id == right.anchor_id:
                continue
            score = _anchor_overlap_score(left, right)
            if score <= 0.0 or score < request.threshold:
                continue
            for current, other in ((left, right), (right, left)):
                existing = overlap_by_anchor.setdefault(
                    current.anchor_id,
                    {
                        "anchor": current,
                        "score": score,
                        "overlapping": set(),
                    },
                )
                existing["score"] = max(float(existing["score"]), score)
                existing["overlapping"].add(other.anchor_id)

    results: list[CitationOverlapPayload] = []
    for anchor_id in sorted(overlap_by_anchor):
        record = overlap_by_anchor[anchor_id]
        anchor = record["anchor"]
        overlapping = sorted(record["overlapping"])
        score = round(float(record["score"]), 4)
        results.append(
            CitationOverlapPayload(
                anchor_id=anchor.anchor_id,
                material_id=anchor.material_id,
                chunk_id=anchor.chunk_id,
                overlap_score=score,
                overlapping_anchors=overlapping,
                recommendation=_overlap_recommendation(score, len(overlapping)),
            )
        )
    return results


# =========================================================================
# S5: Citation source-anchor verification
# =========================================================================

_GENERATED_CITATION_SOURCE_KINDS = {
    "generated_description",
    "generated_figure_description",
    "generated_table_description",
    "generated_equation_description",
    "figure_description",
    "table_description",
    "equation_description",
}


def _normalize_source_kind(value: str) -> str:
    """Normalize source-kind values for deterministic trust rules."""

    return str(value or "local").strip().lower() or "local"


def _dedupe_source_labels(labels: list[str]) -> list[str]:
    """Return stable, non-empty labels while preserving first-seen order."""

    deduped: list[str] = []
    seen: set[str] = set()
    for raw_label in labels:
        label = str(raw_label or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        deduped.append(label)
    return deduped


def _citation_anchor_is_concrete(request: CitationVerificationRequest) -> bool:
    """Return true when a citation can jump to a concrete PDF/material anchor."""

    anchor = request.source_anchor
    if anchor is None:
        return False
    if not str(anchor.material_id or "").strip():
        return False
    if str(anchor.chunk_id or "").strip():
        return True
    if anchor.page is not None:
        return True
    return anchor.bbox is not None


def _citation_text_support_score(request: CitationVerificationRequest) -> float:
    """Score deterministic text overlap between citation/claim text and evidence."""

    evidence_tokens = _citation_overlap_tokens(request.evidence_text)
    candidate_text = " ".join(
        part.strip()
        for part in (request.citation_text, request.claim_text)
        if isinstance(part, str) and part.strip()
    )
    candidate_tokens = _citation_overlap_tokens(candidate_text)
    if not evidence_tokens or not candidate_tokens:
        return 0.0
    return _jaccard_similarity(candidate_tokens, evidence_tokens)


def _citation_verification_status(
    request: CitationVerificationRequest,
) -> tuple[CitationVerificationStatus, str]:
    """Classify citation support without trusting generated descriptions alone."""

    source_kind = _normalize_source_kind(request.source_kind)
    has_anchor = _citation_anchor_is_concrete(request)
    if not has_anchor:
        if source_kind in _GENERATED_CITATION_SOURCE_KINDS:
            return (
                CitationVerificationStatus.UNSUPPORTED,
                "图表/公式等生成描述不能单独作为可信引用；需要 material_id + page/chunk/bbox 指向原始 PDF。",
            )
        return (
            CitationVerificationStatus.UNSUPPORTED,
            "引用缺少可跳回原始 PDF 的 source anchor。",
        )

    support_score = _citation_text_support_score(request)
    if support_score >= 0.2:
        return (
            CitationVerificationStatus.VERIFIED,
            f"引用文本与锚点证据文本存在可复核重叠，overlap={support_score:.2f}。",
        )
    if source_kind in _GENERATED_CITATION_SOURCE_KINDS:
        return (
            CitationVerificationStatus.NEEDS_REVIEW,
            "生成描述已绑定原始 PDF anchor，但仍需要人工或后续语义核验确认描述是否忠实于原文。",
        )
    return (
        CitationVerificationStatus.NEEDS_REVIEW,
        "引用已绑定原始 PDF anchor，但缺少足够的证据文本重叠；需要复核。",
    )


@router.post("/api/citations/verify", response_model=CitationVerificationPayload)
async def verify_citation_source(
    request: CitationVerificationRequest,
) -> CitationVerificationPayload:
    """Verify one citation against a concrete PDF source anchor and persist it."""

    normalized_project_id = request.project_id.strip()
    normalized_citation_id = request.citation_id.strip()
    if not normalized_project_id:
        raise HTTPException(status_code=422, detail="project_id must be non-empty")
    if not normalized_citation_id:
        raise HTTPException(status_code=422, detail="citation_id must be non-empty")

    status, rationale = _citation_verification_status(request)
    anchor_labels = request.source_anchor.source_labels if request.source_anchor is not None else []
    labels = _dedupe_source_labels([*request.source_labels, *anchor_labels])
    verification_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    record = CitationVerificationPayload(
        verification_id=verification_id,
        project_id=normalized_project_id,
        citation_id=normalized_citation_id,
        status=status,
        rationale=rationale,
        source_kind=_normalize_source_kind(request.source_kind),
        source_anchor=request.source_anchor,
        source_labels=labels,
        created_at=now,
        updated_at=now,
    )

    _refresh_citation_verifications_store()
    _citation_verifications_store[verification_id] = record
    _write_citation_verifications(_citation_verifications_store)
    return record


def _record_has_any_source_label(record: CitationVerificationPayload, labels: list[str]) -> bool:
    """Return true when a verification record carries any requested label."""

    if not labels:
        return True
    anchor_labels = record.source_anchor.source_labels if record.source_anchor is not None else []
    all_labels = set(_dedupe_source_labels([*record.source_labels, *anchor_labels]))
    return any(label in all_labels for label in labels)


@router.get("/api/citations/verifications", response_model=CitationVerificationsResponse)
async def list_citation_verifications(
    project_id: str = Query(..., min_length=1),
    citation_id: Optional[str] = Query(None, min_length=1),
    status: Optional[CitationVerificationStatus] = Query(None),
    source_labels: List[str] = Query(None, description="Filter by source labels"),
    material_id: Optional[str] = Query(None, min_length=1),
) -> CitationVerificationsResponse:
    """List persisted citation verification records for a project."""

    records = [
        record
        for record in _refresh_citation_verifications_store().values()
        if record.project_id == project_id
    ]
    if citation_id is not None:
        records = [record for record in records if record.citation_id == citation_id]
    if status is not None:
        records = [record for record in records if record.status == status]
    if material_id is not None:
        records = [
            record
            for record in records
            if record.source_anchor is not None and record.source_anchor.material_id == material_id
        ]
    normalized_labels = _dedupe_source_labels(source_labels or [])
    if normalized_labels:
        records = [
            record
            for record in records
            if _record_has_any_source_label(record, normalized_labels)
        ]

    sorted_records = sorted(records, key=lambda item: (item.created_at, item.verification_id))
    return CitationVerificationsResponse(records=sorted_records, total=len(sorted_records))


# =========================================================================
# E6: Inspiration evidence_refs with source_labels filter
# =========================================================================

@router.get("/api/inspiration/evidence_refs", response_model=EvidenceRefsResponse)
async def get_inspiration_evidence_refs(
    source_labels: List[str] = Query(None, description="Filter by source labels"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> EvidenceRefsResponse:
    """Get inspiration evidence references with source_labels filtering.

    Alias to /api/evidence_refs with inspiration-specific context.
    """
    return await get_evidence_refs(
        project_id=None,
        material_id=None,
        source_labels=source_labels,
        page=page,
        page_size=page_size,
    )
