"""Evidence chain and source label models for API."""

from typing import List, Optional
from pydantic import BaseModel, Field


class SourceLabelPayload(BaseModel):
    """Source label for filtering evidence references."""

    label_id: str
    name: str
    description: str = ""
    color: Optional[str] = None
    created_at: str
    updated_at: str


class CreateSourceLabelRequest(BaseModel):
    """Request to create a source label."""

    name: str
    description: str = ""
    color: Optional[str] = None


class UpdateSourceLabelRequest(BaseModel):
    """Request to update a source label."""

    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None


class EvidenceRefPayload(BaseModel):
    """Evidence reference with optional source labels and bbox."""

    ref_id: str
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
    source_hint: Optional[str] = None
    rank: Optional[int] = None
    bbox: Optional[List[float]] = Field(None, description="[x0, y0, x1, y1] bounding box")
    created_at: str
    updated_at: str


class EvidenceRefsResponse(BaseModel):
    """Response for evidence refs list endpoint."""

    refs: List[EvidenceRefPayload] = Field(default_factory=list)
    total: int = 0
    filtered_by_labels: List[str] = Field(default_factory=list)


class ChunkLocatorPayload(BaseModel):
    """Chunk locator with bbox information."""

    chunk_id: str
    material_id: str
    page: Optional[int] = None
    bbox: Optional[List[float]] = Field(None, description="[x0, y0, x1, y1] bounding box")
    text_preview: str = ""


class DiscussionEvidencePackPayload(BaseModel):
    """Discussion evidence pack persistence payload."""

    pack_id: str
    discussion_id: str
    project_id: str
    query: str
    created_at: str
    snippets: List[dict] = Field(default_factory=list)
    source_labels: List[str] = Field(default_factory=list)


class CitationOverlapPayload(BaseModel):
    """Citation overlap detection result."""

    anchor_id: str
    material_id: str
    chunk_id: str
    overlap_score: float = Field(ge=0.0, le=1.0)
    overlapping_anchors: List[str] = Field(default_factory=list)
    recommendation: str = ""
