"""Typed evidence graph API contract."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from literature_assistant.core.models.evidence import PdfAnchorFields


EvidenceGraphScopeKind = Literal[
    "source",
    "knowledge_item",
    "insight",
    "smart_read_session",
    "question",
    "project",
]
EvidenceGraphNodeType = Literal[
    "source",
    "chunk",
    "paper",
    "concept",
    "claim",
    "method",
    "dataset",
    "metric",
    "finding",
    "limitation",
    "insight",
    "session",
    "agent",
]
EvidenceGraphRelation = Literal[
    "contains",
    "derived_from",
    "cites",
    "supports",
    "contradicts",
    "uses_method",
    "uses_dataset",
    "evaluated_by",
    "mentions",
    "promoted_to",
    "related",
]
EvidenceGraphStatus = Literal["trusted", "candidate", "rejected", "stale"]
EvidenceGraphCreatedBy = Literal[
    "parser",
    "wiki_frontmatter",
    "llm_extraction",
    "user_action",
    "migration",
    "runtime_capture",
    "wiki_graph",
    "source_vault",
]


class EvidenceGraphScope(BaseModel):
    """Scope for a reusable evidence graph request.

    Args:
        kind: Product surface or source-of-truth class being projected.
        ref: Stable id or question text for the scope. Empty is allowed for
            broad project/debug views.
    """

    kind: EvidenceGraphScopeKind
    ref: str = ""


class EvidenceGraphProvenanceRef(PdfAnchorFields):
    """Concrete provenance anchor for a trusted graph relation.

    At least one source/material/chunk identifier is required so graph clicks
    can resolve back to an auditable source instead of becoming decorative
    relationships.
    """

    source_id: str | None = None
    source_vault_id: str | None = None
    chunk_id: str | None = None
    source_vault_chunk_id: str | None = None
    material_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    text_hash: str | None = None
    quote: str = ""

    @model_validator(mode="after")
    def _validate_anchor_identity(self) -> "EvidenceGraphProvenanceRef":
        if self.bbox is not None and self.page is None:
            raise ValueError("bbox provenance requires page")
        identifiers = (
            self.source_id,
            self.source_vault_id,
            self.chunk_id,
            self.source_vault_chunk_id,
            self.material_id,
        )
        if not any(isinstance(value, str) and value.strip() for value in identifiers):
            raise ValueError("provenance ref requires at least one source/material/chunk id")
        return self


class EvidenceGraphNode(BaseModel):
    """Node in the reusable evidence graph payload."""

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    type: EvidenceGraphNodeType
    status: EvidenceGraphStatus = "trusted"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    provenance_refs: list[EvidenceGraphProvenanceRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceGraphEdge(BaseModel):
    """Directed relation in the reusable evidence graph payload."""

    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    relation: EvidenceGraphRelation
    status: EvidenceGraphStatus = "candidate"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    provenance_refs: list[EvidenceGraphProvenanceRef] = Field(default_factory=list)
    created_by: EvidenceGraphCreatedBy
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _trusted_edges_require_provenance(self) -> "EvidenceGraphEdge":
        if self.status == "trusted" and not self.provenance_refs:
            raise ValueError("trusted graph edges require provenance refs")
        return self


class EvidenceGraphPayload(BaseModel):
    """Versioned evidence graph payload shared by Knowledge Workbench and SmartRead."""

    version: Literal["v1"] = "v1"
    scope: EvidenceGraphScope
    updated_at: str
    nodes: list[EvidenceGraphNode] = Field(default_factory=list)
    edges: list[EvidenceGraphEdge] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_edge_endpoints(self) -> "EvidenceGraphPayload":
        node_ids = {node.id for node in self.nodes}
        missing = [
            edge.id
            for edge in self.edges
            if edge.source not in node_ids or edge.target not in node_ids
        ]
        if missing:
            raise ValueError(f"graph edges reference missing nodes: {', '.join(sorted(missing))}")
        return self
