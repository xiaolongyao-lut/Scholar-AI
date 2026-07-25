"""Pure projection of durable citation candidates into the shared graph DTO."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from literature_assistant.core.knowledge_graph.citation_models import CitesCandidate
from literature_assistant.core.knowledge_graph.models import (
    EvidenceGraphEdge,
    EvidenceGraphProvenanceRef,
    EvidenceGraphStatus,
)


def citation_candidate_status(candidate: CitesCandidate) -> EvidenceGraphStatus:
    """Map independent review/freshness axes to the shared display status."""

    if candidate.freshness_status == "stale":
        return "stale"
    if candidate.review_status == "rejected":
        return "rejected"
    if candidate.review_status == "accepted":
        return "trusted"
    return "candidate"


def citation_candidate_provenance_refs(
    candidate: CitesCandidate,
) -> list[EvidenceGraphProvenanceRef]:
    """Return citation-marker and reference-entry locators in stable order."""

    return [
        EvidenceGraphProvenanceRef(
            material_id=candidate.source_material_id,
            chunk_id=candidate.source_chunk_id,
            page=candidate.source_page,
            bbox=candidate.source_bbox,
            bbox_unit=candidate.source_bbox_unit,
            quote=candidate.marker,
        ),
        EvidenceGraphProvenanceRef(
            material_id=candidate.source_material_id,
            chunk_id=candidate.reference_chunk_id,
            page=candidate.reference_page,
            bbox=candidate.reference_bbox,
            bbox_unit=candidate.reference_bbox_unit,
            quote=candidate.reference_text,
        ),
    ]


def build_citation_candidate_graph_edge(
    candidate: CitesCandidate,
    *,
    extra_metadata: Mapping[str, Any] | None = None,
) -> EvidenceGraphEdge:
    """Project one stored candidate without accepting it or writing Wiki.

    Args:
        candidate: Strict stored source-to-target citation candidate.
        extra_metadata: Optional projection-only metadata supplied by a scoped
            project or answer controller. Stored lifecycle fields remain the
            authoritative candidate status.

    Returns:
        One directed ``cites`` edge with both durable PDF locators.
    """

    if not isinstance(candidate, CitesCandidate):
        raise TypeError("candidate must be a CitesCandidate")
    if extra_metadata is not None and not isinstance(extra_metadata, Mapping):
        raise TypeError("extra_metadata must be a mapping or None")
    metadata: dict[str, Any] = {
        "source_store": "citation_candidate_store",
        "project_id": candidate.project_id,
        "candidate_id": candidate.candidate_id,
        "mention_id": candidate.mention_id,
        "batch_id": candidate.batch_id,
        "session_id": candidate.session_id,
        "turn_id": candidate.turn_id,
        "selection_id": candidate.selection_id,
        "review_status": candidate.review_status,
        "freshness_status": candidate.freshness_status,
        "match_method": candidate.match_method,
        "reference_number": candidate.reference_number,
        "source_locator": {
            "material_id": candidate.source_material_id,
            "page": candidate.source_page,
            "chunk_id": candidate.source_chunk_id,
            "bbox": candidate.source_bbox,
            "bbox_unit": (
                candidate.source_bbox_unit.value if candidate.source_bbox_unit is not None else None
            ),
        },
        "reference_locator": {
            "material_id": candidate.source_material_id,
            "page": candidate.reference_page,
            "chunk_id": candidate.reference_chunk_id,
            "bbox": candidate.reference_bbox,
            "bbox_unit": (
                candidate.reference_bbox_unit.value
                if candidate.reference_bbox_unit is not None
                else None
            ),
        },
        "source_version": candidate.source_version,
        "extractor_version": candidate.extractor_version,
        "parser_version": candidate.parser_version,
        "resolver_version": candidate.resolver_version,
        "source_fingerprint": candidate.source_fingerprint,
        "reference_fingerprint": candidate.reference_fingerprint,
        "target_fingerprint": candidate.target_fingerprint,
    }
    if extra_metadata:
        for key, value in extra_metadata.items():
            if key in metadata and metadata[key] != value:
                raise ValueError(f"extra_metadata cannot override stored citation field: {key}")
            metadata[key] = value
    return EvidenceGraphEdge(
        id=candidate.candidate_id,
        source=candidate.source_material_id,
        target=candidate.target_material_id,
        relation="cites",
        direction="directed",
        status=citation_candidate_status(candidate),
        confidence=candidate.confidence,
        provenance_refs=citation_candidate_provenance_refs(candidate),
        created_by="runtime_capture",
        updated_at=candidate.updated_at.isoformat().replace("+00:00", "Z"),
        metadata=metadata,
    )


__all__ = [
    "build_citation_candidate_graph_edge",
    "citation_candidate_provenance_refs",
    "citation_candidate_status",
]
