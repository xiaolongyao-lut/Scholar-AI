"""Evidence chain and source labels API router - /api/evidence_refs, /api/source_labels.

Provides independent evidence_refs API with source_labels filtering (A4/A5),
chunk locator bbox support (A7), discussion evidence_pack persistence (D5),
and citation overlap detection (D8).
"""

from fastapi import APIRouter, HTTPException, Query, Response
from typing import Any, List, Literal, Optional
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
from project_paths import runtime_state_path
from routers.resources_router.endpoints_search_upload import (
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
