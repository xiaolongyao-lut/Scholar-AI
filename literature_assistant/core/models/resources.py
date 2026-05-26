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
    source_folder: str = ""  # User-specified folder for literature files & chunk storage


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


class FigureTableCandidatePayload(BaseModel):
    """Chunk-derived figure/table candidate for Manuscript Studio.

    Args:
        id: Stable candidate identifier within one project.
        kind: Candidate type, currently ``figure`` or ``table``.
        label: Display label such as ``图 1`` or ``表 2``.
        caption: Short caption/description derived from the source chunk.
        material_id: Material that owns the source chunk.
        material_title: Human-readable material title.
        page: One-based page number when the chunk store provides it.
        chunk_id: Source chunk identifier for provenance lookup.
        chunk_index: Source chunk ordinal when available.
        bbox: Optional source layout box reserved for PDF layout extraction.
        asset_path: Optional extracted asset path reserved for image/table crops.
        source: Candidate extraction source. ``chunk_text`` means text-only.
    """

    id: str
    kind: str = Field(pattern="^(figure|table)$")
    label: str
    caption: str
    material_id: str
    material_title: str
    page: Optional[int] = None
    chunk_id: str
    chunk_index: Optional[int] = None
    bbox: Optional[List[float]] = None
    asset_path: Optional[str] = None
    source: str = "chunk_text"


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


class ProjectExportEvidenceProvenancePayload(BaseModel):
    """Source metadata for one project export evidence row."""

    material_title: str
    material_type: str


class ProjectExportEvidenceRowPayload(BaseModel):
    """Academic evidence row derived for project export."""

    evidence_id: str
    material_id: str
    chunk_id: Optional[str] = None
    page: Optional[int] = None
    excerpt: str
    score: Optional[float] = None
    provenance: ProjectExportEvidenceProvenancePayload
    anchor_ids: List[str] = Field(default_factory=list)
    status: str


class ProjectExportCitationChainPayload(BaseModel):
    """Trace from a draft anchor back to its source evidence."""

    anchor_id: str
    section_id: Optional[str] = None
    paragraph_index: Optional[int] = None
    material_id: Optional[str] = None
    evidence_id: Optional[str] = None
    claim_excerpt: str
    source_excerpt: str
    page: Optional[int] = None
    confidence: Optional[float] = None


class ProjectExportReviewFindingPayload(BaseModel):
    """Export-time writing evidence review finding."""

    id: str
    severity: str
    message: str
    draft_id: Optional[str] = None
    section_id: Optional[str] = None
    material_id: Optional[str] = None


class ProjectExportPayload(BaseModel):
    """Project export response for JSON and Markdown formats."""

    project_id: Optional[str] = None
    format: str
    filename: Optional[str] = None
    content: Optional[str] = None
    project: Optional[ProjectPayload] = None
    sections: List[SectionPayload] = Field(default_factory=list)
    drafts: List[DraftPayload] = Field(default_factory=list)
    materials: List[MaterialPayload] = Field(default_factory=list)
    document_count: Optional[int] = None
    evidence_rows: List[ProjectExportEvidenceRowPayload] = Field(default_factory=list)
    citation_chain: List[ProjectExportCitationChainPayload] = Field(default_factory=list)
    review_findings: List[ProjectExportReviewFindingPayload] = Field(default_factory=list)


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
    source_folder: str = ""  # Optional: local folder path where literature files are stored


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
    """Request to build writing associations."""

    project_id: str
    query: str
    draft_id: Optional[str] = None
    section_id: Optional[str] = None
    mode: str = "default"
    ai_enhanced: bool = True


class OutlineItemPayload(BaseModel):
    """Outline item (section/subsection) in hierarchical structure."""

    item_id: str
    project_id: str
    parent_id: Optional[str] = None
    title: str
    level: int = Field(ge=1, le=6, description="Heading level (1-6)")
    order: int = Field(ge=0, description="Display order within parent")
    description: str = ""
    section_id: Optional[str] = None  # Link to WritingSection if exists
    created_at: str
    updated_at: str


class OutlinePayload(BaseModel):
    """Complete outline structure for a project."""

    project_id: str
    items: List[OutlineItemPayload] = Field(default_factory=list)
    updated_at: str


class GenerateOutlineRequest(BaseModel):
    """Request to generate outline via AI."""

    project_id: str
    topic: str
    content_type: str = "academic"
    target_length: Optional[int] = Field(None, description="Target word count")
    focus_areas: List[str] = Field(default_factory=list)
    existing_materials: List[str] = Field(default_factory=list, description="Material IDs to reference")


class CitationSourcePayload(BaseModel):
    """Citation source metadata (not Word-style bibliography).

    Tracks source material metadata for citation anchors in drafts.
    """

    source_id: str
    material_id: str
    project_id: str
    title: str
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    publication: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    citation_count: int = Field(0, description="Number of times cited in project")
    created_at: str
    updated_at: str


class CitationSuggestionPayload(BaseModel):
    """AI-suggested citation for a draft context."""

    material_id: str
    title: str
    excerpt: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    rationale: str
    suggested_position: Optional[int] = Field(None, description="Suggested insertion offset")


class SuggestCitationsRequest(BaseModel):
    """Request to suggest citations via AI."""

    project_id: str
    draft_id: str
    context: str = Field(description="Draft text context for suggestions")
    max_suggestions: int = Field(5, ge=1, le=20)


class FigureAssetPayload(BaseModel):
    """Real figure/table asset (not text-derived candidate).

    Represents actual extracted or uploaded figure/table with asset file.
    Distinct from FigureTableCandidatePayload which is text-only.
    """

    asset_id: str
    project_id: str
    kind: str = Field(pattern="^(figure|table)$")
    caption: str
    numbering: str = Field(description="e.g., 'Figure 1', 'Table 2'")
    material_id: Optional[str] = None
    source_page: Optional[int] = None
    bbox: Optional[List[float]] = None
    asset_path: str = Field(description="Path to extracted image/table file")
    width: Optional[int] = None
    height: Optional[int] = None
    format: Optional[str] = Field(None, description="png, jpg, svg, etc.")
    created_at: str
    updated_at: str


class CreateFigureAssetRequest(BaseModel):
    """Request to create a figure/table asset."""

    project_id: str
    kind: str = Field(pattern="^(figure|table)$")
    caption: str
    numbering: str
    material_id: Optional[str] = None
    source_page: Optional[int] = None
    bbox: Optional[List[float]] = None
    asset_path: str
    width: Optional[int] = None
    height: Optional[int] = None
    format: Optional[str] = None


class SubmitForReviewRequest(BaseModel):
    """Request to submit project for review."""

    project_id: str
    reviewer_email: Optional[str] = None
    message: str = ""
    include_drafts: bool = True
    include_materials: bool = True


class SubmissionResponsePayload(BaseModel):
    """Response for submission request."""

    submission_id: str
    project_id: str
    status: str
    submitted_at: str
    reviewer_email: Optional[str] = None
    package_path: Optional[str] = None


class ExportProjectRequest(BaseModel):
    """Request to export project."""

    project_id: str
    format: str = Field(pattern="^(json|markdown|word|latex|pdf)$")
    include_evidence: bool = True
    include_citations: bool = True


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
