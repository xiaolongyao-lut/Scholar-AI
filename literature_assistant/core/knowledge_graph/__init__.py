"""Shared evidence graph contract and projection helpers."""

from literature_assistant.core.knowledge_graph.models import (
    EvidenceGraphEdge,
    EvidenceGraphNode,
    EvidenceGraphPayload,
    EvidenceGraphProvenanceRef,
    EvidenceGraphScope,
)
from literature_assistant.core.knowledge_graph.projection import (
    build_evidence_graph_from_smart_read_session,
    build_evidence_graph_from_wiki_snapshot,
    empty_evidence_graph,
)

__all__ = [
    "EvidenceGraphEdge",
    "EvidenceGraphNode",
    "EvidenceGraphPayload",
    "EvidenceGraphProvenanceRef",
    "EvidenceGraphScope",
    "build_evidence_graph_from_smart_read_session",
    "build_evidence_graph_from_wiki_snapshot",
    "empty_evidence_graph",
]
