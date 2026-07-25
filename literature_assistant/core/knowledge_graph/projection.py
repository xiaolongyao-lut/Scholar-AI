"""Evidence graph projections from existing local source-of-truth stores."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from literature_assistant.core.graph_payload import adapt_edge, adapt_node
from literature_assistant.core.knowledge_graph.citation_graph_projection import (
    build_citation_candidate_graph_edge,
)
from literature_assistant.core.knowledge_graph.citation_models import CitesCandidate
from literature_assistant.core.knowledge_graph.models import (
    EvidenceGraphEdge,
    EvidenceGraphNode,
    EvidenceGraphPayload,
    EvidenceGraphProvenanceRef,
    EvidenceGraphRelation,
    EvidenceGraphScope,
    default_evidence_graph_direction,
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

MAX_ANSWER_TURN_MESSAGES = 8
MAX_ANSWER_TURN_EVIDENCE_REFS = 128
MAX_ANSWER_CITATION_EDGES = 64
_GRAPH_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")


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
    if scope.kind == "question":
        raise ValueError(
            "question scope requires build_evidence_graph_from_answer_turn with session_id and turn_id"
        )
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

    for index, message in enumerate(messages):
        if not isinstance(message, Mapping):
            continue
        role = _optional_text(message.get("role"))
        content = _optional_text(message.get("content")) or ""
        message_id = _optional_text(message.get("id")) or f"message-{index}"
        if role == "user":
            question_id = f"question:{_stable_token(message_id)}"
            latest_question_id = question_id
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
                    direction="directed",
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
        question_id = latest_question_id
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
                    direction="directed",
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
                        direction="directed",
                        status="trusted",
                        confidence=_optional_float(raw_ref.get("score")),
                        provenance_refs=[provenance],
                        created_by="runtime_capture",
                        updated_at=updated_at,
                        metadata={"source_store": "smart_read_session", "assistant_message_id": message_id},
                    ),
                )

    filtered_nodes = list(nodes_by_id.values())
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


def build_evidence_graph_from_answer_turn(
    session: Mapping[str, Any],
    *,
    session_id: str,
    turn_id: str,
    scope: EvidenceGraphScope,
    citation_candidates: Sequence[CitesCandidate] = (),
) -> EvidenceGraphPayload:
    """Project exactly one persisted answer turn without question-text matching.

    Args:
        session: Persisted SmartRead session mapping containing message records.
        session_id: Exact owning session identity expected in ``session``.
        turn_id: Exact turn identity shared by the user and assistant messages.
        scope: ``question`` scope whose ref is the turn id, or the legacy
            ``smart_read_session`` scope used by the compatibility endpoint.
        citation_candidates: Project-local candidates already filtered to the
            exact session and turn by the read-only controller.

    Returns:
        A bounded read-only graph containing only messages whose persisted
        ``turn_id`` equals the requested turn. Missing turns are represented by
        an empty payload with a stable warning instead of a session-wide fallback.

    Raises:
        TypeError: If ``session`` or ``scope`` has the wrong runtime type.
        ValueError: If identifiers, scope, or persisted session identity are invalid.
    """

    if not isinstance(session, Mapping):
        raise TypeError("session must be a mapping")
    if not isinstance(scope, EvidenceGraphScope):
        raise TypeError("scope must be an EvidenceGraphScope")
    normalized_session_id = _required_graph_identifier(session_id, "session_id")
    normalized_turn_id = _required_graph_identifier(turn_id, "turn_id")
    persisted_session_id = _required_graph_identifier(
        session.get("session_id"),
        "session.session_id",
    )
    if persisted_session_id != normalized_session_id:
        raise ValueError("persisted session id does not match the requested session_id")
    if scope.kind not in {"question", "smart_read_session"}:
        raise ValueError("answer turn graphs require question or smart_read_session scope")
    if scope.kind == "question" and scope.ref.strip() != normalized_turn_id:
        raise ValueError("question graph scope ref must equal turn_id")
    normalized_candidates, candidate_warnings = _answer_citation_candidates(
        citation_candidates,
        project_id=_optional_text(session.get("project_id")),
        session_id=normalized_session_id,
        turn_id=normalized_turn_id,
    )

    raw_messages = session.get("messages")
    messages = raw_messages if isinstance(raw_messages, list) else []
    exact_messages = [
        message
        for message in messages
        if isinstance(message, Mapping)
        and _optional_text(message.get("turn_id")) == normalized_turn_id
    ]
    if not exact_messages:
        return empty_evidence_graph(
            scope,
            warning=(
                "answer_turn_not_found: no persisted messages match the requested "
                "session_id and turn_id."
            ),
        )

    warnings: list[str] = list(candidate_warnings)
    if len(exact_messages) > MAX_ANSWER_TURN_MESSAGES:
        warnings.append(
            f"Answer turn messages were limited to {MAX_ANSWER_TURN_MESSAGES}; "
            f"{len(exact_messages) - MAX_ANSWER_TURN_MESSAGES} messages were omitted."
        )
        exact_messages = exact_messages[:MAX_ANSWER_TURN_MESSAGES]

    bounded_messages: list[dict[str, Any]] = []
    remaining_refs = MAX_ANSWER_TURN_EVIDENCE_REFS
    omitted_refs = 0
    for message in exact_messages:
        bounded_message = dict(message)
        raw_refs = message.get("evidence_refs")
        if isinstance(raw_refs, list):
            kept_refs = raw_refs[:remaining_refs]
            omitted_refs += max(0, len(raw_refs) - len(kept_refs))
            bounded_message["evidence_refs"] = kept_refs
            remaining_refs -= len(kept_refs)
        bounded_messages.append(bounded_message)
    if omitted_refs:
        warnings.append(
            f"Answer turn evidence refs were limited to {MAX_ANSWER_TURN_EVIDENCE_REFS}; "
            f"{omitted_refs} refs were omitted."
        )
    if not any(_optional_text(message.get("role")) == "user" for message in bounded_messages):
        warnings.append("answer_turn_missing_question: the persisted turn has no user message.")

    bounded_session = dict(session)
    bounded_session["session_id"] = normalized_session_id
    bounded_session["messages"] = bounded_messages
    session_scope = (
        EvidenceGraphScope(kind="smart_read_session", ref=normalized_session_id)
        if scope.kind == "question"
        else scope
    )
    payload = build_evidence_graph_from_smart_read_session(
        bounded_session,
        scope=session_scope,
    )
    return _shape_answer_argument_graph(
        payload,
        messages=bounded_messages,
        session_id=normalized_session_id,
        turn_id=normalized_turn_id,
        scope=scope,
        citation_candidates=normalized_candidates,
        warnings=warnings,
    )


def _answer_citation_candidates(
    candidates: Sequence[CitesCandidate],
    *,
    project_id: str | None,
    session_id: str,
    turn_id: str,
) -> tuple[tuple[CitesCandidate, ...], tuple[str, ...]]:
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise TypeError("citation_candidates must be a sequence of CitesCandidate records")
    normalized = tuple(candidates)
    if any(not isinstance(candidate, CitesCandidate) for candidate in normalized):
        raise TypeError("citation_candidates must contain only CitesCandidate records")
    if normalized and project_id is None:
        raise ValueError("answer citation candidates require persisted session project_id")
    if any(
        candidate.project_id != project_id
        or candidate.session_id != session_id
        or candidate.turn_id != turn_id
        for candidate in normalized
    ):
        raise ValueError("answer citation candidates must match project_id, session_id, and turn_id")
    candidate_ids = [candidate.candidate_id for candidate in normalized]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("citation_candidates must not contain duplicate candidate ids")
    ranked = sorted(normalized, key=lambda item: (item.created_at, item.candidate_id))
    if len(ranked) <= MAX_ANSWER_CITATION_EDGES:
        return tuple(ranked), ()
    warning = (
        f"Answer citation relationships were limited to {MAX_ANSWER_CITATION_EDGES}; "
        f"{len(ranked) - MAX_ANSWER_CITATION_EDGES} candidates were omitted."
    )
    return tuple(ranked[:MAX_ANSWER_CITATION_EDGES]), (warning,)


def _shape_answer_argument_graph(
    payload: EvidenceGraphPayload,
    *,
    messages: Sequence[Mapping[str, Any]],
    session_id: str,
    turn_id: str,
    scope: EvidenceGraphScope,
    citation_candidates: Sequence[CitesCandidate],
    warnings: Sequence[str],
) -> EvidenceGraphPayload:
    """Add the answer claim and orient one exact argument chain."""

    nodes_by_id: dict[str, EvidenceGraphNode] = {}
    for node in payload.nodes:
        metadata = {
            **node.metadata,
            "projection_scope": "answer_turn",
            "session_id": session_id,
            "turn_id": turn_id,
        }
        node_type = node.type
        if node.metadata.get("role") == "user":
            metadata["argument_role"] = "question"
        elif node.type == "chunk":
            metadata["argument_role"] = "evidence"
        elif node.type == "source":
            metadata["argument_role"] = "paper"
            node_type = "paper"
        nodes_by_id[node.id] = EvidenceGraphNode.model_validate(
            {
                **node.model_dump(mode="python"),
                "type": node_type,
                "metadata": metadata,
            }
        )

    latest_question_id: str | None = None
    assistant_claims: dict[str, tuple[str, str | None]] = {}
    for index, message in enumerate(messages):
        role = _optional_text(message.get("role"))
        message_id = _optional_text(message.get("id")) or f"message-{index}"
        if role == "user":
            latest_question_id = f"question:{_stable_token(message_id)}"
            continue
        if role != "assistant":
            continue
        claim_id = f"claim:{_stable_token(message_id)}"
        nodes_by_id[claim_id] = EvidenceGraphNode(
            id=claim_id,
            label=_compact_label(message.get("content"), fallback="Answer claim"),
            type="claim",
            status="candidate",
            metadata={
                "source_store": "smart_read_session",
                "projection_scope": "answer_turn",
                "argument_role": "claim",
                "session_id": session_id,
                "turn_id": turn_id,
                "message_id": message_id,
                "role": "assistant",
                "generated_in": _optional_text(message.get("generated_in")),
            },
        )
        assistant_claims[message_id] = (claim_id, latest_question_id)

    edges_by_id: dict[str, EvidenceGraphEdge] = {}
    for edge in payload.edges:
        edge_payload = edge.model_dump(mode="python")
        edge_metadata = {
            **edge.metadata,
            "projection_scope": "answer_turn",
            "session_id": session_id,
            "turn_id": turn_id,
        }
        assistant_message_id = _optional_text(edge.metadata.get("assistant_message_id"))
        if edge.relation == "derived_from" and assistant_message_id in assistant_claims:
            claim_id, _question_id = assistant_claims[assistant_message_id]
            edge_payload.update(
                {
                    "id": f"edge:{_stable_token(claim_id + ':derived_from:' + edge.target)}",
                    "source": claim_id,
                    "metadata": {**edge_metadata, "argument_link": "claim_to_evidence"},
                }
            )
        elif (
            edge.relation == "contains"
            and edge.source.startswith("source:")
            and edge.target.startswith("chunk:")
        ):
            edge_payload.update(
                {
                    "id": f"edge:{_stable_token(edge.target + ':derived_from:' + edge.source)}",
                    "source": edge.target,
                    "target": edge.source,
                    "relation": "derived_from",
                    "direction": "directed",
                    "metadata": {**edge_metadata, "argument_link": "evidence_to_paper"},
                }
            )
        else:
            edge_payload["metadata"] = edge_metadata
        shaped_edge = EvidenceGraphEdge.model_validate(edge_payload)
        edges_by_id.setdefault(shaped_edge.id, shaped_edge)

    for assistant_message_id, (claim_id, question_id) in assistant_claims.items():
        if question_id is None or question_id not in nodes_by_id:
            continue
        edge = EvidenceGraphEdge(
            id=f"edge:{_stable_token(question_id + ':contains:' + claim_id)}",
            source=question_id,
            target=claim_id,
            relation="contains",
            direction="directed",
            status="candidate",
            created_by="runtime_capture",
            updated_at=payload.updated_at,
            metadata={
                "source_store": "smart_read_session",
                "projection_scope": "answer_turn",
                "argument_link": "question_to_claim",
                "session_id": session_id,
                "turn_id": turn_id,
                "assistant_message_id": assistant_message_id,
            },
        )
        edges_by_id.setdefault(edge.id, edge)

    material_node_ids: dict[str, str] = {}
    for node in nodes_by_id.values():
        if node.metadata.get("argument_role") != "paper":
            continue
        for provenance_ref in node.provenance_refs:
            if provenance_ref.material_id:
                material_node_ids.setdefault(provenance_ref.material_id, node.id)
    for candidate in citation_candidates:
        endpoint_labels = {
            candidate.source_material_id: candidate.source_material_id,
            candidate.target_material_id: (
                candidate.target_material_title or candidate.target_material_id
            ),
        }
        for material_id, label in endpoint_labels.items():
            if material_id in material_node_ids:
                continue
            node_id = f"source:{_stable_token(material_id)}"
            nodes_by_id[node_id] = EvidenceGraphNode(
                id=node_id,
                label=_compact_label(label, fallback="Paper"),
                type="paper",
                status="trusted",
                provenance_refs=[EvidenceGraphProvenanceRef(material_id=material_id)],
                metadata={
                    "source_store": "citation_candidate_store",
                    "projection_scope": "answer_turn",
                    "argument_role": "paper",
                    "project_id": candidate.project_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "material_id": material_id,
                },
            )
            material_node_ids[material_id] = node_id
        citation_edge = build_citation_candidate_graph_edge(
            candidate,
            extra_metadata={
                "projection_scope": "answer_turn",
                "argument_link": "paper_cites_paper",
                "session_id": session_id,
                "turn_id": turn_id,
            },
        )
        citation_payload = citation_edge.model_dump(mode="python")
        citation_payload.update(
            {
                "source": material_node_ids[candidate.source_material_id],
                "target": material_node_ids[candidate.target_material_id],
            }
        )
        shaped_citation_edge = EvidenceGraphEdge.model_validate(citation_payload)
        edges_by_id.setdefault(shaped_citation_edge.id, shaped_citation_edge)

    return EvidenceGraphPayload(
        scope=scope,
        updated_at=payload.updated_at,
        nodes=list(nodes_by_id.values()),
        edges=list(edges_by_id.values()),
        warnings=[*warnings, *payload.warnings],
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
    relation = _RELATION_MAP.get(adapted.relation, "related")
    return EvidenceGraphEdge(
        id=edge.edge_id,
        source=edge.source_id,
        target=edge.target_id,
        relation=relation,
        direction=default_evidence_graph_direction(relation),
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


def _required_graph_identifier(value: object, field_name: str) -> str:
    text = _required_text(value, field_name)
    if not _GRAPH_IDENTIFIER_RE.fullmatch(text):
        raise ValueError(f"{field_name} has an unsupported identifier shape")
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
