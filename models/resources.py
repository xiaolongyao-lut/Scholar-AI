"""Writing resource API models used by the FastAPI adapter."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CitationAnchorPayload(BaseModel):
    """Stable citation anchor metadata exchanged with the frontend editor."""

    id: str
    materialId: Optional[str] = None
    token: str
    startOffset: int
    endOffset: int
    ordinal: int


class ProjectPayload(BaseModel):
    """Writing project response."""

    project_id: str
    title: str
    description: str
    status: str
    content_type: str
    created_at: str
    updated_at: str
    user_id: Optional[str] = None
    tags: List[str]


class SectionPayload(BaseModel):
    """Writing section response."""

    section_id: str
    project_id: str
    title: str
    order: int
    description: str
    created_at: str
    updated_at: str


class MaterialPayload(BaseModel):
    """Project-scoped material response used by the reference drawer."""

    material_id: str
    project_id: str
    title: str
    title_en: str = ""
    summary: str = ""
    summary_en: str = ""
    type: str = "reference"
    focus_points: List[str] = Field(default_factory=list)
    focus_points_en: List[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class DraftPayload(BaseModel):
    """Writing draft response."""

    draft_id: str
    project_id: str
    section_id: Optional[str] = None
    title: str
    content: str
    status: str
    created_at: str
    updated_at: str
    last_edited_by: Optional[str] = None
    citation_anchors: List[CitationAnchorPayload] = Field(default_factory=list)


class RevisionPayload(BaseModel):
    """Writing revision response."""

    revision_id: str
    draft_id: str
    project_id: str
    content: str
    revision_number: int
    created_at: str
    created_by: Optional[str] = None
    message: str
    citation_anchors: List[CitationAnchorPayload] = Field(default_factory=list)


class AssociationSignalPayload(BaseModel):
    """Ranked writing-association evidence item."""

    source_type: str
    source_id: str
    title: str
    excerpt: str
    score: float
    shared_terms: List[str] = Field(default_factory=list)
    rationale: str


class AssociationAnglePayload(BaseModel):
    """Bridgeable writing angle synthesized from multiple signals."""

    angle_id: str
    title: str
    prompt: str
    supporting_source_ids: List[str] = Field(default_factory=list)
    shared_terms: List[str] = Field(default_factory=list)
    confidence: float


class EvidenceGapPayload(BaseModel):
    """Coverage gap that weakens downstream drafting quality."""

    gap: str
    severity: str
    recommendation: str


class WritingAssociationPayload(BaseModel):
    """Full associative-writing response payload."""

    project_id: str
    query: str
    generated_at: str
    draft_id: Optional[str] = None
    section_id: Optional[str] = None
    mode: str
    ai_enhanced: bool
    focus_terms: List[str] = Field(default_factory=list)
    memory_used: bool
    memory_hit_count: int
    related_signals: List[AssociationSignalPayload] = Field(default_factory=list)
    association_angles: List[AssociationAnglePayload] = Field(default_factory=list)
    continuation_prompts: List[str] = Field(default_factory=list)
    evidence_gaps: List[EvidenceGapPayload] = Field(default_factory=list)
    recommended_memory_queries: List[str] = Field(default_factory=list)


class CreateProjectRequest(BaseModel):
    """Request to create a writing project."""

    title: str
    description: str = ""
    content_type: str = "general"  # academic, technical, creative, business, general
    user_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class CreateSectionRequest(BaseModel):
    """Request to create a writing section."""

    project_id: str
    title: str
    order: int
    description: str = ""


class CreateMaterialRequest(BaseModel):
    """Request to create a project-scoped reference material."""

    project_id: str
    title: str
    title_en: str = ""
    summary: str = ""
    summary_en: str = ""
    type: str = "reference"
    focus_points: List[str] = Field(default_factory=list)
    focus_points_en: List[str] = Field(default_factory=list)


class CreateDraftRequest(BaseModel):
    """Request to create a writing draft."""

    project_id: str
    section_id: Optional[str] = None
    title: str = ""
    content: str = ""
    edited_by: Optional[str] = None
    citation_anchors: List[CitationAnchorPayload] = Field(default_factory=list)


class SaveDraftRequest(BaseModel):
    """Request to save draft content."""

    content: str
    edited_by: Optional[str] = None
    citation_anchors: List[CitationAnchorPayload] = Field(default_factory=list)


class BuildAssociationRequest(BaseModel):
    """Request to build associative writing guidance for a project."""

    project_id: str
    query: str
    draft_id: Optional[str] = None
    section_id: Optional[str] = None
    mode: str = Field(default="no_ai", pattern="^(ai|no_ai)$")
    use_memory: bool = True
    memory_query: Optional[str] = None
    wing: Optional[str] = None
    room: Optional[str] = None
    retrieval_hits: List[Dict[str, Any]] = Field(default_factory=list)
    memory_limit: int = Field(default=4, ge=1, le=12)
    signal_limit: int = Field(default=6, ge=1, le=12)
    angle_limit: int = Field(default=3, ge=1, le=6)
