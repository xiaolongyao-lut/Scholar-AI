"""Evidence chain and source label models for API."""

from datetime import date
from enum import Enum
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .tool_outcome import ToolOutcome


class PdfBboxUnit(str, Enum):
    """Coordinate unit carried by PDF evidence anchors."""

    NORMALIZED_RATIO = "normalized_ratio"
    NORMALIZED_1000 = "normalized_1000"
    PDF_POINTS = "pdf_points"
    CSS_PIXELS = "css_pixels"


PDF_URL_BBOX_UNIT = PdfBboxUnit.NORMALIZED_RATIO


def coerce_pdf_bbox(value: Any) -> Optional[List[float]]:
    """Return a four-float bbox for API boundary validation.

    Args:
        value: JSON-like value expected to be a four-number sequence.

    Returns:
        A list of four finite floats, or ``None`` when the value is absent or
        malformed.
    """

    try:
        return _coerce_pdf_bbox_or_raise(value)
    except ValueError:
        return None


def pdf_bbox_matches_unit(value: Any, unit: PdfBboxUnit) -> bool:
    """Return whether a bbox can be interpreted in the declared unit."""

    bbox = coerce_pdf_bbox(value)
    if bbox is None:
        return False
    if unit == PdfBboxUnit.NORMALIZED_RATIO:
        x, y, width, height = bbox
        return (
            x >= 0.0
            and y >= 0.0
            and width > 0.0
            and height > 0.0
            and x <= 1.0
            and y <= 1.0
            and x + width <= 1.0001
            and y + height <= 1.0001
        )
    if unit == PdfBboxUnit.NORMALIZED_1000:
        return all(0.0 <= item <= 1000.0 for item in bbox)
    return all(item >= 0.0 for item in bbox)


def _coerce_pdf_bbox_or_raise(value: Any) -> Optional[List[float]]:
    """Coerce bbox values while preserving explicit validation failures."""

    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("bbox must contain exactly four numbers")
    bbox: List[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError("bbox must contain exactly four finite numbers")
        number = float(item)
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError("bbox must contain exactly four finite numbers")
        bbox.append(number)
    return bbox


class PdfAnchorFields(BaseModel):
    """Shared bbox/unit fields for PDF evidence anchor payloads."""

    bbox: Optional[List[float]] = Field(
        None,
        description="[x, y, width, height] when bbox_unit is normalized_ratio",
    )
    bbox_unit: Optional[PdfBboxUnit] = Field(
        None,
        description="Coordinate unit for bbox. Missing legacy values default to normalized_ratio.",
    )

    @field_validator("bbox", mode="before")
    @classmethod
    def _validate_bbox_shape(cls, value: Any) -> Optional[List[float]]:
        """Reject malformed bbox values before route handlers see them."""

        return _coerce_pdf_bbox_or_raise(value)

    @model_validator(mode="after")
    def _validate_bbox_unit(self) -> "PdfAnchorFields":
        """Keep bbox and bbox_unit paired so callers never infer silently."""

        if self.bbox is None:
            self.bbox_unit = None
            return self
        unit = self.bbox_unit or PDF_URL_BBOX_UNIT
        if not pdf_bbox_matches_unit(self.bbox, unit):
            raise ValueError(f"bbox is outside the declared {unit.value} coordinate range")
        self.bbox_unit = unit
        return self


class PdfEvidenceAnchorPayload(PdfAnchorFields):
    """Canonical PDF anchor exchanged across evidence, graph, reader, and writing."""

    material_id: str = Field(min_length=1)
    page: Optional[int] = Field(None, ge=1)
    page_label: Optional[str] = None
    chunk_id: Optional[str] = None
    selected_text: str = ""
    source_kind: str = "local"
    source_labels: List[str] = Field(default_factory=list)


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


class EvidenceRefPayload(PdfAnchorFields):
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
    created_at: str
    updated_at: str


class EvidenceRefsResponse(BaseModel):
    """Response for evidence refs list endpoint."""

    refs: List[EvidenceRefPayload] = Field(default_factory=list)
    total: int = 0
    filtered_by_labels: List[str] = Field(default_factory=list)


class ChunkLocatorPayload(PdfAnchorFields):
    """Chunk locator with bbox information."""

    chunk_id: str
    material_id: str
    page: Optional[int] = None
    chunk_index: Optional[int] = None
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


class EvidencePackBuildRequest(BaseModel):
    """Request to build a query-scoped evidence pack from project chunks.

    Args:
        project_id: Project whose already-indexed chunk store is searched.
        query: Non-empty research question or section-local retrieval query.
        section_id: Optional draft/outline section id kept for traceability.
        top_k: Maximum evidence refs returned by the lexical fallback path.
    """

    project_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=4096)
    section_id: Optional[str] = Field(default=None, max_length=128)
    top_k: int = Field(default=10, ge=1, le=50)


class EvidencePackReferencePayload(BaseModel):
    """MCP-safe evidence ref derived from a backend search ref.

    Args:
        project_id: Project that owns the chunk ref.
        source_type: Evidence source family; wiki refs are bounded resources
            and are not copied into project chunks.
        ref_id: Agent bridge resource id in ``kind:id`` form.
        read_endpoint: Bounded reader endpoint with explicit project scope.
        chunk_id: Stable chunk identifier in the project chunk store.
        material_id: Material that owns the chunk.
        page: One-based source page when persisted in metadata.
        lexical_score: Score from the local lexical retrieval path.
        rerank_score: Optional rerank score; ``None`` when rerank did not run.
        citation_anchor: Stable local citation anchor for draft traceability.
        figure_candidate: Optional future figure/table candidate id.
        summary: Bounded summary safe for model context.
        suitable_for_body: Whether the ref is safe to cite in body prose.
        source_title: Optional display title for non-project resources.
        source_path: Optional bounded source path for non-project resources.
        joint_score: Optional fused project/wiki score from weighted RRF.
    """

    project_id: str = Field(min_length=1)
    source_type: Literal["project", "wiki"] = "project"
    ref_id: str = Field(min_length=1)
    read_endpoint: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    material_id: str = Field(min_length=1)
    page: Optional[int] = Field(default=None, ge=1)
    lexical_score: float = Field(ge=0.0)
    rerank_score: Optional[float] = Field(default=None, ge=0.0)
    citation_anchor: str = Field(min_length=1, max_length=260)
    figure_candidate: Optional[str] = Field(default=None, max_length=260)
    summary: str = Field(min_length=1, max_length=300)
    suitable_for_body: bool = True
    source_title: Optional[str] = Field(default=None, max_length=160)
    source_path: Optional[str] = Field(default=None, max_length=240)
    joint_score: Optional[float] = Field(default=None, ge=0.0)


class RetrievalQrelsStatusPayload(BaseModel):
    """Quality-label gate for retrieval evaluation state.

    Args:
        status: Highest available local qrels review state for the project.
        candidate_qrels_count: Candidate TREC qrels rows still awaiting review.
        reviewed_qrels_count: Reviewed judgment rows available before promotion.
        canonical_qrels_count: Canonical TREC qrels rows available for metrics.
        semantic_quality_claim_allowed: True only when canonical qrels exist.
        quality_claim: Short public claim token for UI/API gating.
        notes: Bounded reviewer notes explaining why quality claims are gated.
    """

    schema_version: Literal["retrieval-qrels-status/v1"] = "retrieval-qrels-status/v1"
    status: Literal["missing", "candidate", "reviewed", "canonical"] = "missing"
    candidate_qrels_count: int = Field(default=0, ge=0)
    reviewed_qrels_count: int = Field(default=0, ge=0)
    canonical_qrels_count: int = Field(default=0, ge=0)
    semantic_quality_claim_allowed: bool = False
    quality_claim: Literal[
        "no_qrels_available",
        "candidate_qrels_review_required",
        "reviewed_qrels_promotion_required",
        "canonical_qrels_available",
    ] = "no_qrels_available"
    notes: List[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _validate_quality_gate(self) -> "RetrievalQrelsStatusPayload":
        """Prevent candidate/reviewed qrels from being reported as quality proof."""

        if self.semantic_quality_claim_allowed:
            if self.status != "canonical" or self.canonical_qrels_count <= 0:
                raise ValueError("semantic quality claims require canonical qrels")
            self.quality_claim = "canonical_qrels_available"
        elif self.status == "canonical" and self.canonical_qrels_count > 0:
            raise ValueError("canonical qrels must enable the semantic quality gate")
        return self


class EvidenceRetrievalDiagnosticsPayload(BaseModel):
    """Machine-readable retrieval provenance for writing/evidence audits.

    Args:
        retrieval_method: Effective retrieval path used for this response.
        embedding_status: Whether dense embeddings were used, skipped, or unavailable.
        rerank_status: Whether reranking was active, skipped, or unavailable.
        fallback_reason: Short reason when the path degraded to lexical retrieval.
        project_weight: Weight assigned to project-local chunks in this build.
        wiki_weight: Weight assigned to wiki recall in this build.
        joint_recall: Optional wiki+project fusion diagnostics. Wiki hits are
            reported here without being coerced into project chunk refs.
        qrels_status: Whether retrieval quality can be claimed from canonical
            qrels, or is still blocked by missing/candidate/reviewed labels.
        reasoning_trace: Auditable retrieval-decision summary, not private
            model chain-of-thought.
        notes: Bounded operational notes safe to show in chat/tool transcripts.
    """

    retrieval_method: Literal["lexical", "hybrid", "hybrid_rerank"] = "lexical"
    embedding_status: Literal["active", "skipped", "unavailable"] = "unavailable"
    rerank_status: Literal["active", "skipped", "unavailable"] = "unavailable"
    fallback_reason: str = Field(default="", max_length=240)
    project_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    wiki_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    joint_recall: dict[str, Any] = Field(default_factory=dict)
    qrels_status: RetrievalQrelsStatusPayload = Field(default_factory=RetrievalQrelsStatusPayload)
    reasoning_trace: List[str] = Field(default_factory=list, max_length=16)
    notes: List[str] = Field(default_factory=list, max_length=12)


class EvidencePackBuildResponse(BaseModel):
    """Response for the evidence-pack builder endpoint.

    Args:
        evidence_pack_ref: Stable ref id for this deterministic build result.
        project_id: Project searched.
        query: Query string used for retrieval.
        section_id: Optional section id carried from the request.
        retrieval_method: Actual retrieval method used by the backend.
        rerank_status: Whether reranking actively ran, was skipped, or unavailable.
        total: Number of evidence refs returned after truncation.
        truncated: Whether more positive lexical hits existed than returned.
        retrieval_diagnostics: Explicit embedding/rerank visibility for agents.
        outcome: Agent-facing status, attempts, and safe next action.
        evidence_refs: MCP-safe evidence refs with no raw chunk body fields.
    """

    evidence_pack_ref: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    section_id: Optional[str] = None
    retrieval_method: Literal["lexical", "hybrid", "hybrid_rerank"] = "lexical"
    rerank_status: Literal["active", "skipped", "unavailable"] = "unavailable"
    total: int = Field(ge=0)
    truncated: bool = False
    retrieval_diagnostics: EvidenceRetrievalDiagnosticsPayload = Field(
        default_factory=EvidenceRetrievalDiagnosticsPayload
    )
    outcome: Optional[ToolOutcome] = None
    evidence_refs: List[EvidencePackReferencePayload] = Field(default_factory=list)


class JournalMetricEvidencePayload(BaseModel):
    """Evidence row for journal-level metrics without treating metrics as relevance.

    Args:
        journal_title: Human-readable journal title.
        issn: Optional ISSN/eISSN used to disambiguate journal titles.
        metric_name: Metric label such as JIF, CiteScore, CAS partition, or CCF.
        metric_year: Year the metric applies to.
        metric_value: Display value copied from the cited source.
        source_tier: Whether the source is official or an aggregator.
        source_name: Provider or publisher name.
        source_url: URL or local evidence URI for the metric source.
        verified_at: Date this value was checked.
        verified_by: Local verifier or automation label.
        claim_scope: How the value may be used in Scholar AI outputs.
        notes: Bounded caveats, especially for aggregated sources.
    """

    schema_version: Literal["scholar-ai-journal-metric-evidence/v1"] = (
        "scholar-ai-journal-metric-evidence/v1"
    )
    journal_title: str = Field(min_length=1, max_length=240)
    issn: Optional[str] = Field(default=None, max_length=32)
    metric_name: str = Field(min_length=1, max_length=80)
    metric_year: int = Field(ge=1900, le=2200)
    metric_value: str = Field(min_length=1, max_length=120)
    source_tier: Literal["official", "aggregated"]
    source_name: str = Field(min_length=1, max_length=160)
    source_url: str = Field(min_length=1, max_length=1000)
    verified_at: date
    verified_by: str = Field(min_length=1, max_length=120)
    claim_scope: Literal["official_metric", "screening_reference"]
    notes: List[str] = Field(default_factory=list, max_length=8)

    @field_validator(
        "journal_title",
        "issn",
        "metric_name",
        "metric_value",
        "source_name",
        "source_url",
        "verified_by",
        mode="before",
    )
    @classmethod
    def _normalize_metric_text(cls, value: Any) -> Optional[str]:
        """Trim metric fields so equality and serialization stay stable."""

        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("journal metric text fields must be strings")
        text = value.strip()
        if not text:
            return None
        return text

    @field_validator("notes", mode="before")
    @classmethod
    def _normalize_notes(cls, value: Any) -> List[str]:
        """Keep notes bounded and non-empty for UI-safe caveats."""

        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("notes must be a list")
        notes: List[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("notes must be strings")
            text = item.strip()
            if text:
                notes.append(text[:240])
            if len(notes) >= 8:
                break
        return notes

    @model_validator(mode="after")
    def _validate_metric_claim_scope(self) -> "JournalMetricEvidencePayload":
        """Prevent aggregated metrics from being represented as official proof."""

        if self.source_tier == "aggregated" and self.claim_scope == "official_metric":
            raise ValueError("aggregated journal metrics cannot support official_metric claims")
        if self.source_tier == "official" and self.claim_scope != "official_metric":
            self.notes = [
                *self.notes,
                "Official source provided, but this row is intentionally scoped as a screening reference.",
            ][:8]
        return self


class JournalMetricEvidenceSet(BaseModel):
    """Small collection wrapper for journal metric evidence rows."""

    schema_version: Literal["scholar-ai-journal-metric-evidence-set/v1"] = (
        "scholar-ai-journal-metric-evidence-set/v1"
    )
    records: List[JournalMetricEvidencePayload] = Field(default_factory=list)

    @property
    def official_count(self) -> int:
        """Return the number of official metric evidence rows."""

        return sum(1 for record in self.records if record.source_tier == "official")

    @property
    def aggregated_count(self) -> int:
        """Return the number of aggregated metric evidence rows."""

        return sum(1 for record in self.records if record.source_tier == "aggregated")

    @property
    def has_official_metric_claim(self) -> bool:
        """Return whether at least one row can support an official metric claim."""

        return any(record.claim_scope == "official_metric" for record in self.records)

    def summary(self) -> dict[str, Any]:
        """Return JSON-safe counts for API, MCP, and report surfaces."""

        return {
            "schema_version": self.schema_version,
            "total": len(self.records),
            "official_count": self.official_count,
            "aggregated_count": self.aggregated_count,
            "has_official_metric_claim": self.has_official_metric_claim,
        }


class CitationOverlapPayload(BaseModel):
    """Citation overlap detection result."""

    anchor_id: str
    material_id: str
    chunk_id: str
    overlap_score: float = Field(ge=0.0, le=1.0)
    overlapping_anchors: List[str] = Field(default_factory=list)
    recommendation: str = ""


class CitationVerificationStatus(str, Enum):
    """Deterministic citation-verification states stored for review."""

    VERIFIED = "verified"
    NEEDS_REVIEW = "needs_review"
    UNSUPPORTED = "unsupported"


class CitationVerificationAnchorPayload(PdfAnchorFields):
    """Concrete source anchor used to verify one citation.

    Args:
        material_id: Original PDF or material that owns the evidence.
        chunk_id: Optional extracted chunk tied to the PDF source.
        page: One-based PDF page number when known.
        evidence_ref_id: Optional saved evidence reference id.
        source_label: Optional primary source label.
        source_labels: Additional labels used for filtering and review.
    """

    material_id: Optional[str] = None
    chunk_id: Optional[str] = None
    page: Optional[int] = Field(None, ge=1)
    evidence_ref_id: Optional[str] = None
    source_label: Optional[str] = None
    source_labels: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_pdf_anchor(self) -> "CitationVerificationAnchorPayload":
        """Reject bbox-only citation anchors because PDF focus requires a page."""

        if self.bbox is not None and self.page is None:
            raise ValueError("citation source bbox requires page")
        return self


class CitationVerificationRequest(BaseModel):
    """Request to verify and record one citation against a source anchor.

    Args:
        project_id: Non-empty project id.
        citation_id: Stable citation or editor-anchor id.
        claim_text: Claim text that the citation is meant to support.
        citation_text: Quoted or displayed citation text.
        evidence_text: Source evidence text when available for deterministic
            overlap checks.
        source_kind: Source class, for example local, web, mcp, figure_description.
        source_anchor: Concrete PDF anchor that makes the citation auditable.
        source_labels: Labels copied from the source or evidence ref.
    """

    project_id: str = Field(min_length=1, max_length=128)
    citation_id: str = Field(min_length=1, max_length=128)
    claim_text: str = Field(default="", max_length=4096)
    citation_text: str = Field(default="", max_length=4096)
    evidence_text: str = Field(default="", max_length=8192)
    source_kind: str = Field(default="local", max_length=64)
    source_anchor: Optional[CitationVerificationAnchorPayload] = None
    source_labels: List[str] = Field(default_factory=list)


class CitationVerificationPayload(BaseModel):
    """Persisted citation verification result."""

    verification_id: str
    project_id: str
    citation_id: str
    status: CitationVerificationStatus
    rationale: str
    source_kind: str
    source_anchor: Optional[CitationVerificationAnchorPayload] = None
    source_labels: List[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class CitationVerificationsResponse(BaseModel):
    """Response for citation verification records."""

    records: List[CitationVerificationPayload] = Field(default_factory=list)
    total: int = 0
