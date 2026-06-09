"""Evidence graph projections from existing local source-of-truth stores."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from literature_assistant.core.graph_payload import adapt_edge, adapt_node
from literature_assistant.core.knowledge_graph.models import (
    EvidenceGraphEdge,
    EvidenceGraphNode,
    EvidenceGraphPayload,
    EvidenceGraphProvenanceRef,
    EvidenceGraphRelation,
    EvidenceGraphScope,
)
from literature_assistant.core.wiki.graph import (
    WikiGraphEdge,
    WikiGraphNode,
    WikiGraphSnapshot,
    utc_now_iso,
)


_NODE_KIND_MAP: dict[str, str] = {
    "source": "source",
    "material": "source",
    "paper": "paper",
    "concept": "concept",
    "claim": "claim",
    "method": "method",
    "dataset": "dataset",
    "metric": "metric",
    "finding": "finding",
    "limitation": "limitation",
    "insight": "insight",
    "session": "session",
    "agent": "agent",
}

_RELATION_MAP: dict[str, EvidenceGraphRelation] = {
    "supports": "supports",
    "contradicts": "contradicts",
    "extends": "derived_from",
    "uses": "mentions",
    "produces": "derived_from",
    "measures": "evaluated_by",
    "cites": "cites",
    "related": "related",
}


def empty_evidence_graph(scope: EvidenceGraphScope, *, warning: str | None = None) -> EvidenceGraphPayload:
    """Return an empty v1 evidence graph payload."""

    warnings = [warning] if warning else []
    return EvidenceGraphPayload(scope=scope, updated_at=utc_now_iso(), nodes=[], edges=[], warnings=warnings)


def build_evidence_graph_from_wiki_snapshot(
    snapshot: WikiGraphSnapshot,
    *,
    scope: EvidenceGraphScope,
    node_filter: Iterable[str] | None = None,
) -> EvidenceGraphPayload:
    """Project a Wiki graph snapshot into the shared Evidence Graph v1 contract."""

    if not isinstance(snapshot, WikiGraphSnapshot):
        raise TypeError("snapshot must be a WikiGraphSnapshot")
    if not isinstance(scope, EvidenceGraphScope):
        raise TypeError("scope must be an EvidenceGraphScope")

    allowed = set(node_filter) if node_filter is not None else _node_ids_for_scope(snapshot, scope)
    nodes = [
        _node_from_wiki(node)
        for node in snapshot.nodes
        if allowed is None or node.node_id in allowed
    ]
    node_ids = {node.id for node in nodes}
    edges = [
        _edge_from_wiki(edge)
        for edge in snapshot.edges
        if edge.source_id in node_ids and edge.target_id in node_ids
    ]
    return EvidenceGraphPayload(
        scope=scope,
        updated_at=snapshot.updated_at or utc_now_iso(),
        nodes=nodes,
        edges=edges,
    )


def build_evidence_graph_from_smart_read_session(
    session: Mapping[str, Any],
    *,
    scope: EvidenceGraphScope,
) -> EvidenceGraphPayload:
    """Project one persisted SmartRead session into Evidence Graph v1."""

    if not isinstance(session, Mapping):
        raise TypeError("session must be a mapping")
    if not isinstance(scope, EvidenceGraphScope):
        raise TypeError("scope must be an EvidenceGraphScope")
    session_id = _required_text(session.get("session_id"), "session.session_id")
    messages = session.get("messages")
    if not isinstance(messages, list):
        messages = []

    updated_at = _optional_text(session.get("updated_at")) or utc_now_iso()
    nodes_by_id: dict[str, EvidenceGraphNode] = {
        f"session:{session_id}": EvidenceGraphNode(
            id=f"session:{session_id}",
            label=_optional_text(session.get("title")) or f"SmartRead {session_id}",
            type="session",
            status="trusted",
            metadata={
                "source_store": "smart_read_session",
                "session_id": session_id,
                "project_id": _optional_text(session.get("project_id")),
            },
        )
    }
    edges_by_id: dict[str, EvidenceGraphEdge] = {}
    latest_question_id: str | None = None
    matched_question_ids: set[str] = set()

    for index, message in enumerate(messages):
        if not isinstance(message, Mapping):
            continue
        role = _optional_text(message.get("role"))
        content = _optional_text(message.get("content")) or ""
        message_id = _optional_text(message.get("id")) or f"message-{index}"
        if role == "user":
            question_id = f"question:{_stable_token(message_id)}"
            latest_question_id = question_id
            if _question_matches_scope(message, scope):
                matched_question_ids.add(question_id)
            nodes_by_id[question_id] = EvidenceGraphNode(
                id=question_id,
                label=_compact_label(content, fallback="SmartRead question"),
                type="claim",
                status="trusted",
                metadata={
                    "source_store": "smart_read_session",
                    "session_id": session_id,
                    "message_id": message_id,
                    "role": role,
                },
            )
            _put_edge(
                edges_by_id,
                EvidenceGraphEdge(
                    id=f"edge:{_stable_token(session_id + ':contains:' + message_id)}",
                    source=f"session:{session_id}",
                    target=question_id,
                    relation="contains",
                    status="candidate",
                    created_by="runtime_capture",
                    updated_at=updated_at,
                    metadata={"source_store": "smart_read_session", "trust_reason": "structural_session_edge"},
                ),
            )
            continue

        if role != "assistant":
            continue
        raw_refs = message.get("evidence_refs")
        if not isinstance(raw_refs, list):
            continue
        question_id = _nearest_question_for_assistant(latest_question_id, matched_question_ids, scope)
        for ref_index, raw_ref in enumerate(raw_refs):
            if not isinstance(raw_ref, Mapping):
                continue
            provenance = _provenance_ref_from_mapping(raw_ref)
            if provenance is None:
                continue
            material_id = _optional_text(raw_ref.get("material_id")) or _optional_text(raw_ref.get("source"))
            chunk_id = _optional_text(raw_ref.get("chunk_id"))
            source_node_id = f"source:{_stable_token(material_id or chunk_id or session_id)}"
            chunk_node_id = f"chunk:{_stable_token(chunk_id or material_id or f'{message_id}-{ref_index}')}"
            nodes_by_id.setdefault(
                source_node_id,
                EvidenceGraphNode(
                    id=source_node_id,
                    label=_compact_label(material_id or _optional_text(raw_ref.get("source")) or "SmartRead source"),
                    type="source",
                    status="trusted",
                    provenance_refs=[provenance],
                    metadata={"source_store": "smart_read_session", "session_id": session_id},
                ),
            )
            nodes_by_id[chunk_node_id] = EvidenceGraphNode(
                id=chunk_node_id,
                label=_compact_label(raw_ref.get("quote") or raw_ref.get("text") or chunk_id or "Evidence chunk"),
                type="chunk",
                status="trusted",
                confidence=_optional_float(raw_ref.get("score")),
                provenance_refs=[provenance],
                metadata={
                    "source_store": "smart_read_session",
                    "session_id": session_id,
                    "message_id": message_id,
                    "chunk_id": chunk_id,
                    "rank": raw_ref.get("rank"),
                    "source_kind": raw_ref.get("source_kind"),
                },
            )
            _put_edge(
                edges_by_id,
                EvidenceGraphEdge(
                    id=f"edge:{_stable_token(source_node_id + ':contains:' + chunk_node_id)}",
                    source=source_node_id,
                    target=chunk_node_id,
                    relation="contains",
                    status="trusted",
                    provenance_refs=[provenance],
                    created_by="runtime_capture",
                    updated_at=updated_at,
                    metadata={"source_store": "smart_read_session"},
                ),
            )
            if question_id is not None and question_id in nodes_by_id:
                _put_edge(
                    edges_by_id,
                    EvidenceGraphEdge(
                        id=f"edge:{_stable_token(question_id + ':derived_from:' + chunk_node_id)}",
                        source=question_id,
                        target=chunk_node_id,
                        relation="derived_from",
                        status="trusted",
                        confidence=_optional_float(raw_ref.get("score")),
                        provenance_refs=[provenance],
                        created_by="runtime_capture",
                        updated_at=updated_at,
                        metadata={"source_store": "smart_read_session", "assistant_message_id": message_id},
                    ),
                )

    filtered_nodes = _filter_session_nodes_for_scope(list(nodes_by_id.values()), list(edges_by_id.values()), matched_question_ids, scope)
    filtered_ids = {node.id for node in filtered_nodes}
    filtered_edges = [
        edge for edge in edges_by_id.values()
        if edge.source in filtered_ids and edge.target in filtered_ids
    ]
    warnings: list[str] = []
    if len(filtered_nodes) <= 1:
        warnings.append("SmartRead session has no evidence refs available for graph projection.")
    return EvidenceGraphPayload(
        scope=scope,
        updated_at=updated_at,
        nodes=filtered_nodes,
        edges=filtered_edges,
        warnings=warnings,
    )


def _node_from_wiki(node: WikiGraphNode) -> EvidenceGraphNode:
    adapted = adapt_node(node)
    metadata = dict(adapted.metadata or {})
    metadata.setdefault("source_store", "wiki")
    metadata.setdefault("page_path", node.page_path)
    provenance_refs = _provenance_refs_from_adapted(adapted.source_ref, adapted.evidence_refs, metadata)
    graph_type = _node_type_from_kind(node.kind, adapted.type)
    return EvidenceGraphNode(
        id=node.node_id,
        label=node.title or node.node_id,
        type=graph_type,
        status="trusted",
        confidence=adapted.confidence,
        provenance_refs=provenance_refs,
        metadata=metadata,
    )


def _edge_from_wiki(edge: WikiGraphEdge) -> EvidenceGraphEdge:
    adapted = adapt_edge(edge)
    metadata = dict(adapted.metadata or {})
    metadata.setdefault("source_store", "wiki")
    metadata.setdefault("wiki_edge_type", edge.edge_type.value)
    provenance_refs = _provenance_refs_from_adapted(adapted.source_ref, adapted.evidence_refs, metadata)
    status = "trusted" if provenance_refs else "candidate"
    if not provenance_refs:
        metadata.setdefault("trust_reason", "missing_provenance")
    return EvidenceGraphEdge(
        id=edge.edge_id,
        source=edge.source_id,
        target=edge.target_id,
        relation=_RELATION_MAP.get(adapted.relation, "related"),
        status=status,
        confidence=adapted.confidence,
        provenance_refs=provenance_refs,
        created_by="wiki_graph",
        updated_at=edge.metadata.get("updated_at") if isinstance(edge.metadata.get("updated_at"), str) else utc_now_iso(),
        metadata=metadata,
    )


def _node_type_from_kind(kind: str, adapted_type: str) -> str:
    normalized = (kind or adapted_type or "").strip().lower()
    mapped = _NODE_KIND_MAP.get(normalized)
    if mapped:
        return mapped
    if adapted_type == "material":
        return "source"
    if adapted_type in _NODE_KIND_MAP:
        return adapted_type
    return "concept"


def _provenance_refs_from_adapted(source_ref: Any, evidence_refs: Any, metadata: Mapping[str, Any]) -> list[EvidenceGraphProvenanceRef]:
    refs: list[EvidenceGraphProvenanceRef] = []
    for raw in _metadata_ref_candidates(metadata):
        ref = _provenance_ref_from_mapping(raw)
        if ref is not None:
            refs.append(ref)
    if source_ref is not None:
        ref = _provenance_ref_from_mapping(_modelish_to_mapping(source_ref))
        if ref is not None:
            refs.append(ref)
    if isinstance(evidence_refs, Sequence) and not isinstance(evidence_refs, (str, bytes)):
        for evidence_ref in evidence_refs:
            ref = _provenance_ref_from_mapping(_modelish_to_mapping(evidence_ref))
            if ref is not None:
                refs.append(ref)
    return _dedupe_provenance_refs(refs)


def _metadata_ref_candidates(metadata: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    candidates: list[Mapping[str, Any]] = []
    raw_source_ref = metadata.get("source_ref")
    if isinstance(raw_source_ref, Mapping):
        candidates.append(raw_source_ref)
    raw_refs = metadata.get("evidence_refs")
    if isinstance(raw_refs, Sequence) and not isinstance(raw_refs, (str, bytes)):
        candidates.extend(item for item in raw_refs if isinstance(item, Mapping))
    direct_keys = {
        "source_id",
        "source_vault_id",
        "chunk_id",
        "source_vault_chunk_id",
        "material_id",
        "page",
        "bbox",
        "bbox_unit",
        "text_hash",
        "quote",
    }
    if any(key in metadata for key in direct_keys):
        candidates.append({key: metadata[key] for key in direct_keys if key in metadata})
    return candidates


def _modelish_to_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, Mapping) else {}
    if hasattr(value, "dict"):
        dumped = value.dict()
        return dumped if isinstance(dumped, Mapping) else {}
    return {}


def _provenance_ref_from_mapping(raw: Mapping[str, Any]) -> EvidenceGraphProvenanceRef | None:
    payload: dict[str, Any] = {}
    for key in (
        "source_id",
        "source_vault_id",
        "chunk_id",
        "source_vault_chunk_id",
        "material_id",
        "page",
        "bbox",
        "bbox_unit",
        "text_hash",
        "quote",
    ):
        if key in raw and raw[key] not in (None, ""):
            payload[key] = raw[key]
    text = raw.get("text") or raw.get("selected_text") or raw.get("compressed_text")
    if "text_hash" not in payload and isinstance(text, str) and text.strip():
        payload["text_hash"] = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    if "quote" not in payload and isinstance(text, str):
        payload["quote"] = text.strip()[:500]
    try:
        return EvidenceGraphProvenanceRef.model_validate(payload)
    except ValueError:
        return None


def _dedupe_provenance_refs(refs: Sequence[EvidenceGraphProvenanceRef]) -> list[EvidenceGraphProvenanceRef]:
    seen: set[str] = set()
    deduped: list[EvidenceGraphProvenanceRef] = []
    for ref in refs:
        key = ref.model_dump_json()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def _put_edge(edges_by_id: dict[str, EvidenceGraphEdge], edge: EvidenceGraphEdge) -> None:
    edges_by_id.setdefault(edge.id, edge)


def _node_ids_for_scope(snapshot: WikiGraphSnapshot, scope: EvidenceGraphScope) -> set[str] | None:
    if not scope.ref.strip() or scope.kind in {"question", "project"}:
        return None
    matched = {node.node_id for node in snapshot.nodes if _node_matches_scope(node, scope)}
    if not matched:
        return set()
    adjacent = set(matched)
    for edge in snapshot.edges:
        if edge.source_id in matched:
            adjacent.add(edge.target_id)
        if edge.target_id in matched:
            adjacent.add(edge.source_id)
    return adjacent


def _node_matches_scope(node: WikiGraphNode, scope: EvidenceGraphScope) -> bool:
    ref = scope.ref.strip()
    if not ref:
        return True
    candidates = {
        node.node_id,
        node.page_path,
        node.title,
        str(node.frontmatter_id or ""),
    }
    metadata = node.metadata or {}
    for key in ("material_id", "source_id", "source_vault_id", "candidate_id", "insight_id", "session_id"):
        value = metadata.get(key)
        if isinstance(value, str):
            candidates.add(value)
    source_ref = metadata.get("source_ref")
    if isinstance(source_ref, Mapping):
        for key in ("material_id", "source_id", "source_vault_id", "chunk_id", "source_vault_chunk_id"):
            value = source_ref.get(key)
            if isinstance(value, str):
                candidates.add(value)
    if scope.kind == "insight" and node.kind != "insight" and ref not in candidates:
        return False
    return ref in candidates


def _required_text(value: object, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{field_name} must be a non-empty string")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if 0.0 <= number <= 1.0 else None
    if isinstance(value, str) and value.strip():
        try:
            number = float(value.strip())
        except ValueError:
            return None
        return number if 0.0 <= number <= 1.0 else None
    return None


def _stable_token(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("stable token input must not be empty")
    safe = "".join(char if char.isalnum() or char in "._:-" else "-" for char in text).strip("-")
    if safe and len(safe) <= 80:
        return safe
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]
    prefix = safe[:48].strip("-") if safe else "id"
    return f"{prefix}-{digest}"


def _compact_label(value: object, *, fallback: str = "Evidence") -> str:
    text = _optional_text(value) or fallback
    collapsed = " ".join(text.split())
    return collapsed[:120] if len(collapsed) > 120 else collapsed


def _question_matches_scope(message: Mapping[str, Any], scope: EvidenceGraphScope) -> bool:
    if scope.kind != "question" or not scope.ref.strip():
        return False
    ref = scope.ref.strip()
    return ref in {
        _optional_text(message.get("id")) or "",
        _optional_text(message.get("content")) or "",
    }


def _nearest_question_for_assistant(
    latest_question_id: str | None,
    matched_question_ids: set[str],
    scope: EvidenceGraphScope,
) -> str | None:
    if scope.kind == "question" and scope.ref.strip() and matched_question_ids:
        return sorted(matched_question_ids)[-1]
    return latest_question_id


def _filter_session_nodes_for_scope(
    nodes: list[EvidenceGraphNode],
    edges: list[EvidenceGraphEdge],
    matched_question_ids: set[str],
    scope: EvidenceGraphScope,
) -> list[EvidenceGraphNode]:
    if scope.kind != "question" or not scope.ref.strip() or not matched_question_ids:
        return nodes
    keep = set(matched_question_ids)
    keep.update(node.id for node in nodes if node.type == "session")
    for edge in edges:
        if edge.source in matched_question_ids and edge.relation == "derived_from":
            keep.add(edge.target)
    evidence_nodes = set(keep)
    for edge in edges:
        if edge.relation == "contains" and edge.target in evidence_nodes:
            keep.add(edge.source)
    return [node for node in nodes if node.id in keep]
