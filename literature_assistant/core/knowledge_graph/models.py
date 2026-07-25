"""Typed evidence graph API contract."""

from __future__ import annotations

from collections.abc import Mapping
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
EvidenceGraphDirection = Literal["directed", "undirected"]
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


_RELATION_DIRECTIONS: dict[EvidenceGraphRelation, EvidenceGraphDirection] = {
    "contains": "directed",
    "derived_from": "directed",
    "cites": "directed",
    "supports": "directed",
    "contradicts": "directed",
    "uses_method": "directed",
    "uses_dataset": "directed",
    "evaluated_by": "directed",
    "mentions": "directed",
    "promoted_to": "directed",
    "related": "undirected",
}


def default_evidence_graph_direction(
    relation: EvidenceGraphRelation,
) -> EvidenceGraphDirection:
    """Return the controlled direction for an evidence-graph relation.

    Args:
        relation: Valid relation from the public evidence-graph vocabulary.

    Returns:
        The direction required by the relation contract.

    Raises:
        ValueError: If a runtime caller bypasses typing with an unknown relation.
    """

    try:
        return _RELATION_DIRECTIONS[relation]
    except KeyError as exc:
        raise ValueError(f"unsupported evidence graph relation: {relation!r}") from exc


def _directed_direction_default() -> EvidenceGraphDirection:
    """Provide a schema-neutral fallback for legacy model construction."""

    return "directed"


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
    """Relation in the reusable evidence graph payload with explicit direction."""

    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    relation: EvidenceGraphRelation
    direction: EvidenceGraphDirection = Field(
        default_factory=_directed_direction_default,
        description=(
            "First-class edge direction. Legacy inputs that omit it are upgraded "
            "from the controlled relation vocabulary before validation."
        ),
    )
    status: EvidenceGraphStatus = "candidate"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    provenance_refs: list[EvidenceGraphProvenanceRef] = Field(default_factory=list)
    created_by: EvidenceGraphCreatedBy
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy_direction(cls, value: Any) -> Any:
        if not isinstance(value, Mapping) or "direction" in value:
            return value
        relation = value.get("relation")
        if not isinstance(relation, str) or relation not in _RELATION_DIRECTIONS:
            return value
        upgraded = dict(value)
        upgraded["direction"] = _RELATION_DIRECTIONS[relation]
        return upgraded

    @model_validator(mode="after")
    def _validate_relation_contract(self) -> "EvidenceGraphEdge":
        expected_direction = default_evidence_graph_direction(self.relation)
        if self.direction != expected_direction:
            raise ValueError(
                f"{self.relation} graph edges require direction={expected_direction}"
            )
        if self.direction == "undirected" and self.target < self.source:
            self.source, self.target = self.target, self.source
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
