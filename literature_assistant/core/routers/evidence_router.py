"""Evidence chain and source labels API router - /api/evidence_refs, /api/source_labels.

Provides independent evidence_refs API with source_labels filtering (A4/A5),
chunk locator bbox support (A7), discussion evidence_pack persistence (D5),
and citation overlap detection (D8).
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import uuid

from models import (
    SourceLabelPayload,
    CreateSourceLabelRequest,
    UpdateSourceLabelRequest,
    EvidenceRefPayload,
    EvidenceRefsResponse,
    ChunkLocatorPayload,
    DiscussionEvidencePackPayload,
    CitationOverlapPayload,
)

router = APIRouter(tags=["Evidence"])


# In-memory stores (TODO: replace with persistent storage)
_source_labels_store: dict[str, SourceLabelPayload] = {}
_evidence_refs_store: dict[str, EvidenceRefPayload] = {}
_discussion_packs_store: dict[str, DiscussionEvidencePackPayload] = {}


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
    refs = list(_evidence_refs_store.values())

    # Apply filters
    if project_id:
        # TODO: Add project_id to EvidenceRefPayload if needed
        pass

    if material_id:
        refs = [r for r in refs if r.material_id == material_id]

    if source_labels:
        refs = [
            r for r in refs
            if any(label in r.source_labels for label in source_labels)
        ]

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


class CreateEvidenceRefRequest(BaseModel):
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
    bbox: Optional[List[float]] = Field(None, description="[x0, y0, x1, y1] bounding box")


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
        created_at=now,
        updated_at=now,
    )

    _evidence_refs_store[ref_id] = ref
    return ref


# =========================================================================
# A5: Source labels CRUD
# =========================================================================

@router.get("/api/source_labels", response_model=List[SourceLabelPayload])
async def list_source_labels() -> List[SourceLabelPayload]:
    """List all source labels."""
    return list(_source_labels_store.values())


@router.post("/api/source_labels", response_model=SourceLabelPayload)
async def create_source_label(request: CreateSourceLabelRequest) -> SourceLabelPayload:
    """Create a new source label."""
    label_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    label = SourceLabelPayload(
        label_id=label_id,
        name=request.name,
        description=request.description,
        color=request.color,
        created_at=now,
        updated_at=now,
    )

    _source_labels_store[label_id] = label
    return label


@router.get("/api/source_labels/{label_id}", response_model=SourceLabelPayload)
async def get_source_label(label_id: str) -> SourceLabelPayload:
    """Get a source label by ID."""
    label = _source_labels_store.get(label_id)
    if not label:
        raise HTTPException(status_code=404, detail=f"Source label not found: {label_id}")
    return label


@router.put("/api/source_labels/{label_id}", response_model=SourceLabelPayload)
async def update_source_label(
    label_id: str,
    request: UpdateSourceLabelRequest,
) -> SourceLabelPayload:
    """Update a source label."""
    label = _source_labels_store.get(label_id)
    if not label:
        raise HTTPException(status_code=404, detail=f"Source label not found: {label_id}")

    now = datetime.now(timezone.utc).isoformat()

    updated = SourceLabelPayload(
        label_id=label.label_id,
        name=request.name if request.name is not None else label.name,
        description=request.description if request.description is not None else label.description,
        color=request.color if request.color is not None else label.color,
        created_at=label.created_at,
        updated_at=now,
    )

    _source_labels_store[label_id] = updated
    return updated


@router.delete("/api/source_labels/{label_id}")
async def delete_source_label(label_id: str) -> dict[str, str]:
    """Delete a source label."""
    if label_id not in _source_labels_store:
        raise HTTPException(status_code=404, detail=f"Source label not found: {label_id}")

    del _source_labels_store[label_id]
    return {"message": f"Source label {label_id} deleted"}


# =========================================================================
# A7: Chunk locator with bbox
# =========================================================================

@router.get("/api/chunks/{chunk_id}/locator", response_model=ChunkLocatorPayload)
async def get_chunk_locator(chunk_id: str) -> ChunkLocatorPayload:
    """Get chunk locator with bbox information.

    Returns bounding box coordinates for PDF layout extraction.
    """
    # TODO: Integrate with chunk_vector_store to get actual bbox
    # For now, return mock data
    return ChunkLocatorPayload(
        chunk_id=chunk_id,
        material_id="",
        page=None,
        bbox=None,
        text_preview="",
    )


# =========================================================================
# D5: Discussion evidence_pack persistence
# =========================================================================

class SaveEvidencePackRequest(BaseModel):
    """Request to save discussion evidence pack."""
    project_id: str
    query: str
    snippets: List[dict] = Field(default_factory=list)
    source_labels: List[str] = Field(default_factory=list)


@router.post("/api/discussions/{discussion_id}/evidence_pack", response_model=DiscussionEvidencePackPayload)
async def save_discussion_evidence_pack(
    discussion_id: str,
    request: SaveEvidencePackRequest,
) -> DiscussionEvidencePackPayload:
    """Save evidence pack for a discussion session."""
    pack_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    pack = DiscussionEvidencePackPayload(
        pack_id=pack_id,
        discussion_id=discussion_id,
        project_id=request.project_id,
        query=request.query,
        created_at=now,
        snippets=request.snippets,
        source_labels=request.source_labels,
    )

    _discussion_packs_store[pack_id] = pack
    return pack


@router.get("/api/discussions/{discussion_id}/evidence_pack", response_model=DiscussionEvidencePackPayload)
async def get_discussion_evidence_pack(discussion_id: str) -> DiscussionEvidencePackPayload:
    """Get evidence pack for a discussion session."""
    # Find pack by discussion_id
    for pack in _discussion_packs_store.values():
        if pack.discussion_id == discussion_id:
            return pack

    raise HTTPException(status_code=404, detail=f"Evidence pack not found for discussion: {discussion_id}")


# =========================================================================
# D8: Citation overlap detector
# =========================================================================

class DetectOverlapRequest(BaseModel):
    """Request to detect citation overlap."""
    project_id: str
    draft_id: Optional[str] = None
    threshold: float = Field(0.7, ge=0.0, le=1.0, description="Overlap threshold")


@router.post("/api/citations/detect_overlap", response_model=List[CitationOverlapPayload])
async def detect_citation_overlap(request: DetectOverlapRequest) -> List[CitationOverlapPayload]:
    """Detect overlapping citations in a project or draft.

    Identifies citation anchors that reference the same or highly similar chunks.
    """
    # TODO: Implement actual overlap detection logic
    # For now, return empty list
    return []


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
