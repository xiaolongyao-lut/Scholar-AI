"""GraphPayload v0 — single-question subgraph response shape.

The viewer-only subgraph lives in front of the
existing wiki-graph storage. This module defines the v0 envelope, the
node/edge/source/evidence sub-shapes, and the adapter that maps an
existing :class:`literature_assistant.core.wiki.graph.WikiGraphSnapshot`
into the new payload without touching the legacy
``/api/wiki/graph`` debug endpoint.
"""

from __future__ import annotations

from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, Field, ValidationError

from literature_assistant.core.models.evidence import PdfAnchorFields
from literature_assistant.core.wiki.graph import (
    WikiGraphEdge,
    WikiGraphEdgeType,
    WikiGraphNode,
    WikiGraphSnapshot,
    utc_now_iso,
)

NodeType = Literal[
    "claim",
    "method",
    "dataset",
    "metric",
    "limitation",
    "concept",
    "material",
    "agent",
    "evidence",
]

EdgeRelation = Literal[
    "supports",
    "contradicts",
    "extends",
    "uses",
    "produces",
    "measures",
    "cites",
    "related",
]

ScopeKind = Literal["question", "material", "concept"]


class SourceRef(PdfAnchorFields):
    material_id: str = Field(min_length=1)
    page: int | None = Field(None, ge=1)
    chunk_id: str | None = None


class EvidenceRef(PdfAnchorFields):
    material_id: str = Field(min_length=1)
    page: int | None = Field(None, ge=1)
    chunk_id: str | None = None
    text: str
    score: float | None = None


class GraphNode(BaseModel):
    id: str
    label: str
    type: NodeType
    material_id: str | None = None
    source_ref: SourceRef | None = None
    evidence_refs: list[EvidenceRef] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] | None = None


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relation: EdgeRelation
    material_id: str | None = None
    source_ref: SourceRef | None = None
    evidence_refs: list[EvidenceRef] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] | None = None


class GraphScope(BaseModel):
    kind: ScopeKind
    ref: str


class GraphPayloadV0(BaseModel):
    version: Literal["v0"] = "v0"
    scope: GraphScope
    updated_at: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


# ----- adapter -------------------------------------------------------------

# WikiGraphEdgeType (21 variants) collapses to the v0 controlled vocab.
# Anything that doesn't have a closer mapping falls back to ``related``.
_RELATION_MAP: dict[WikiGraphEdgeType, EdgeRelation] = {
    WikiGraphEdgeType.supports: "supports",
    WikiGraphEdgeType.contradicts: "contradicts",
    WikiGraphEdgeType.challenges: "contradicts",
    WikiGraphEdgeType.critiques_concept: "contradicts",
    WikiGraphEdgeType.extends: "extends",
    WikiGraphEdgeType.extends_concept: "extends",
    WikiGraphEdgeType.improves_on: "extends",
    WikiGraphEdgeType.builds_on: "extends",
    WikiGraphEdgeType.derived_from: "extends",
    WikiGraphEdgeType.uses_concept: "uses",
    WikiGraphEdgeType.depends_on: "uses",
    WikiGraphEdgeType.introduces_concept: "produces",
    WikiGraphEdgeType.cites: "cites",
    WikiGraphEdgeType.surveys: "cites",
    WikiGraphEdgeType.compares_against: "related",
    WikiGraphEdgeType.same_problem_as: "related",
    WikiGraphEdgeType.similar_method_to: "related",
    WikiGraphEdgeType.complementary_to: "related",
    WikiGraphEdgeType.related_to: "related",
    WikiGraphEdgeType.wikilink: "related",
}


def _node_type_from_kind(kind: str) -> tuple[NodeType, dict[str, Any]]:
    """Map a wiki-node kind to the v0 controlled NodeType.

    Returns the node type plus extra metadata to merge (preserves the
    original kind when we had to coerce to ``concept``).
    """
    normalised = (kind or "").strip().lower()
    if normalised in ("claim", "method", "dataset", "metric", "limitation", "material", "agent"):
        return normalised, {}  # type: ignore[return-value]
    if normalised in ("concept", "page", "topic", "wiki", ""):
        return "concept", {} if normalised == "concept" else {"original_kind": kind}
    return "concept", {"original_kind": kind}


# 维度提示：根据 wiki node kind 推一个默认的「思维角色」标签。
# 前端 dimensionGraph 缺失时用启发式，这里只是把后端已经知道的语义显式落到 payload，
# 让 SmartRead / 写作 / WikiWorkbench 拿到一致的维度。
_DIMENSION_BY_KIND: dict[str, str] = {
    "claim": "observation",
    "method": "mechanism",
    "concept": "mechanism",
    "dataset": "evidence",
    "metric": "evidence",
    "material": "evidence",
    "evidence": "evidence",
    "paper": "evidence",
    "limitation": "boundary",
    "boundary": "boundary",
    "agent": "next_action",
    "topic": "question",
    "question": "question",
}


def _reasoning_dimension_from_kind(kind: str) -> str | None:
    """Return a reasoning-dimension hint for a wiki node kind, or None if unknown."""
    normalised = (kind or "").strip().lower()
    return _DIMENSION_BY_KIND.get(normalised)


def _confidence_from_edge(edge: WikiGraphEdge) -> float | None:
    """Reduce ``weight`` (0..1) and qualitative ``confidence`` into one number.

    ``weight`` is already normalised in ``_EDGE_WEIGHTS``. The text
    ``confidence`` field is "low" / "medium" / "high" (or empty); we
    multiply by 0.5 / 0.75 / 1.0 respectively, leaving unknown values as
    a passthrough of weight.
    """
    if edge.weight is None:
        return None
    bias = {"low": 0.5, "medium": 0.75, "high": 1.0}.get((edge.confidence or "").strip().lower(), 1.0)
    value = max(0.0, min(1.0, float(edge.weight) * bias))
    return round(value, 4)


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _source_ref_from_mapping(value: Any) -> SourceRef | None:
    raw = _mapping(value)
    if raw is None:
        return None
    try:
        return SourceRef.model_validate(dict(raw))
    except ValidationError:
        return None


def _evidence_ref_from_mapping(value: Any) -> EvidenceRef | None:
    raw = _mapping(value)
    if raw is None:
        return None
    try:
        return EvidenceRef.model_validate(dict(raw))
    except ValidationError:
        return None


def _source_ref_from_evidence_ref(ref: EvidenceRef | None) -> SourceRef | None:
    if ref is None:
        return None
    try:
        return SourceRef.model_validate(
            {
                "material_id": ref.material_id,
                "page": ref.page,
                "chunk_id": ref.chunk_id,
                "bbox": ref.bbox,
                "bbox_unit": ref.bbox_unit,
            }
        )
    except ValidationError:
        return None


def _metadata_evidence_refs(metadata: Mapping[str, Any]) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []
    for raw_ref in _mapping_list(metadata.get("evidence_refs")):
        ref = _evidence_ref_from_mapping(raw_ref)
        if ref is not None:
            refs.append(ref)
    return refs


def _metadata_source_ref(metadata: Mapping[str, Any], evidence_refs: Sequence[EvidenceRef]) -> SourceRef | None:
    source_ref = _source_ref_from_mapping(metadata.get("source_ref"))
    if source_ref is not None:
        return source_ref
    for ref in evidence_refs:
        source_ref = _source_ref_from_evidence_ref(ref)
        if source_ref is not None:
            return source_ref
    return None


def adapt_node(node: WikiGraphNode) -> GraphNode:
    node_type, extra_meta = _node_type_from_kind(node.kind)
    merged_meta: dict[str, Any] = dict(node.metadata or {})
    merged_meta.update(extra_meta)
    evidence_refs = _metadata_evidence_refs(merged_meta)
    source_ref = _metadata_source_ref(merged_meta, evidence_refs)
    material_id = source_ref.material_id if source_ref is not None else None
    if material_id is None:
        raw_material_id = merged_meta.get("material_id")
        material_id = raw_material_id.strip() if isinstance(raw_material_id, str) and raw_material_id.strip() else None
    # page_path is the canonical wiki path; keep it under metadata so the
    # frontend can build a wiki link without inventing a new field.
    merged_meta.setdefault("page_path", node.page_path)
    if node.frontmatter_id:
        merged_meta.setdefault("frontmatter_id", node.frontmatter_id)
    if node.status:
        merged_meta.setdefault("status", node.status)
    # 在 payload 里显式声明 reasoning_dimension（设计文档 Slice 4）。
    # ``setdefault`` 保证调用方已显式标注的维度不会被覆盖。
    dimension_hint = _reasoning_dimension_from_kind(node.kind)
    if dimension_hint is not None:
        merged_meta.setdefault("reasoning_dimension", dimension_hint)
    return GraphNode(
        id=node.node_id,
        label=node.title or node.node_id,
        type=node_type,
        material_id=material_id,
        source_ref=source_ref,
        evidence_refs=evidence_refs or None,
        metadata=merged_meta or None,
    )


def adapt_edge(edge: WikiGraphEdge) -> GraphEdge:
    relation = _RELATION_MAP.get(edge.edge_type, "related")
    metadata: dict[str, Any] = dict(edge.metadata or {})
    # Preserve the precise wiki edge_type so callers that care about the
    # full ontology can recover it; viewer ignores this field.
    metadata.setdefault("wiki_edge_type", edge.edge_type.value)
    if edge.source_path:
        metadata.setdefault("source_path", edge.source_path)
    if edge.target_path:
        metadata.setdefault("target_path", edge.target_path)
    # Wiki edges carry a free-text ``evidence`` blurb but no real
    # material backing. Storing it as evidence_refs with a fake
    # material_id="wiki" would make the viewer think it has a PDF to
    # jump to — keep evidence_refs strictly for refs that *do* point
    # at a material, and surface the wiki blurb via metadata instead.
    if edge.evidence:
        metadata.setdefault("evidence_text", edge.evidence)
    evidence_refs = _metadata_evidence_refs(metadata)
    source_ref = _metadata_source_ref(metadata, evidence_refs)
    material_id = source_ref.material_id if source_ref is not None else None
    if material_id is None:
        raw_material_id = metadata.get("material_id")
        material_id = raw_material_id.strip() if isinstance(raw_material_id, str) and raw_material_id.strip() else None
    return GraphEdge(
        id=edge.edge_id,
        source=edge.source_id,
        target=edge.target_id,
        relation=relation,
        material_id=material_id,
        source_ref=source_ref,
        evidence_refs=evidence_refs or None,
        confidence=_confidence_from_edge(edge),
        metadata=metadata or None,
    )


def adapt_snapshot(
    snapshot: WikiGraphSnapshot,
    *,
    scope: GraphScope,
    node_filter: Iterable[str] | None = None,
) -> GraphPayloadV0:
    """Adapter: WikiGraphSnapshot → GraphPayload v0.

    ``node_filter`` lets the endpoint scope to a subgraph (e.g. one
    question's blast-radius node ids). When ``None`` the full snapshot
    is returned, which is the cheapest debug surface for KG-1.
    """
    allowed = set(node_filter) if node_filter is not None else None
    nodes = [
        adapt_node(node)
        for node in snapshot.nodes
        if allowed is None or node.node_id in allowed
    ]
    node_ids = {n.id for n in nodes}
    edges = [
        adapt_edge(edge)
        for edge in snapshot.edges
        if edge.source_id in node_ids and edge.target_id in node_ids
    ]
    return GraphPayloadV0(
        scope=scope,
        updated_at=snapshot.updated_at or utc_now_iso(),
        nodes=nodes,
        edges=edges,
    )


def empty_payload(scope: GraphScope) -> GraphPayloadV0:
    """Return a well-formed empty payload for "no data yet" responses."""
    return GraphPayloadV0(scope=scope, updated_at=utc_now_iso(), nodes=[], edges=[])


__all__ = [
    "EdgeRelation",
    "EvidenceRef",
    "GraphEdge",
    "GraphNode",
    "GraphPayloadV0",
    "GraphScope",
    "NodeType",
    "ScopeKind",
    "SourceRef",
    "adapt_edge",
    "adapt_node",
    "adapt_snapshot",
    "empty_payload",
]
