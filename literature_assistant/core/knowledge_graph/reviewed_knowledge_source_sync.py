"""Source-mutation adapters for the reviewed-knowledge ledger.

This module deliberately owns no Wiki or candidate state.  It translates a
material-level source event into the existing per-fact freshness contract so
that every invalidation remains CAS-bound and individually auditable.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from literature_assistant.core.knowledge_graph.reviewed_knowledge_models import (
    AcceptedGraphFact,
    FactSourceRevision,
    ReviewedKnowledgeFreshnessRequest,
    ReviewedKnowledgeMutationResult,
)
from literature_assistant.core.knowledge_graph.reviewed_knowledge_store import (
    ReviewedKnowledgeStore,
)
from literature_assistant.core.project_paths import project_data_path

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_FACT_PAGE = 500


def _require_identifier(value: str, field_name: str) -> str:
    """Validate a project/material identifier before it reaches a ledger query."""

    normalized = str(value or "").strip()
    if not _ID_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} has an unsupported identifier shape")
    return normalized


def _require_source_fingerprint(value: str) -> str:
    """Validate the wire-format source fingerprint used by provenance records."""

    normalized = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise ValueError("source_fingerprint must use sha256:<64 lowercase hex>")
    return normalized


def _require_occurred_at(value: datetime) -> datetime:
    """Normalize an event timestamp to aware UTC without inventing local time."""

    if not isinstance(value, datetime):
        raise TypeError("occurred_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("occurred_at must include a timezone")
    return value.astimezone(timezone.utc)


def _deleted_source_fingerprint(project_id: str, material_id: str) -> str:
    """Return a deterministic non-content fingerprint for a deletion event."""

    payload = f"scholar-ai:material-deleted:v1:{project_id}:{material_id}".encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _stale_operation_id(
    *,
    project_id: str,
    material_id: str,
    fact_id: str,
    current_state_sha256: str,
    source_fingerprint: str,
    source_version: str,
    extractor_version: str,
    parser_version: str,
) -> str:
    """Build a stable idempotency key for one observed source transition."""

    payload = "|".join(
        (
            project_id,
            material_id,
            fact_id,
            current_state_sha256,
            source_fingerprint,
            source_version,
            extractor_version,
            parser_version,
        )
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:40]
    return f"material-source-stale:{digest}"


def _fresh_facts_for_material(
    store: ReviewedKnowledgeStore,
    *,
    project_id: str,
    material_id: str,
) -> tuple[AcceptedGraphFact, ...]:
    """Read all active fresh facts that may reference one material.

    The store exposes bounded pages, so pagination is explicit.  Facts are
    collected before mutation to avoid offset drift while individual CAS
    transitions move rows from ``fresh`` to ``stale``.
    """

    facts: list[AcceptedGraphFact] = []
    offset = 0
    while True:
        page = store.list_facts(
            project_id=project_id,
            freshness_status="fresh",
            availability_status="active",
            limit=_MAX_FACT_PAGE,
            offset=offset,
        )
        if not page:
            break
        facts.extend(
            fact
            for fact in page
            if any(provenance.material_id == material_id for provenance in fact.provenance)
        )
        if len(page) < _MAX_FACT_PAGE:
            break
        offset += len(page)
    return tuple(facts)


def _matches_observed_revision(
    provenance: FactSourceRevision,
    *,
    material_id: str,
    source_fingerprint: str,
    source_version: str,
    extractor_version: str,
    parser_version: str,
) -> bool:
    """Return whether one provenance row already represents the observed revision."""

    return provenance.identity_tuple() == (
        material_id,
        source_fingerprint,
        source_version,
        extractor_version,
        parser_version,
    )


def mark_material_facts_stale(
    *,
    store: ReviewedKnowledgeStore,
    project_id: str,
    material_id: str,
    source_fingerprint: str,
    source_version: str,
    extractor_version: str,
    parser_version: str,
    reason: str,
    changed_by: str,
    occurred_at: datetime,
) -> tuple[ReviewedKnowledgeMutationResult, ...]:
    """Mark all matching active reviewed facts stale for one source revision.

    Args:
        store: Project-scoped reviewed-knowledge ledger.
        project_id: Owning Scholar AI project.
        material_id: Source material whose revision changed or disappeared.
        source_fingerprint: New source identity, including deletion markers.
        source_version: Caller-controlled source revision token.
        extractor_version: Extractor identity observed for the new revision.
        parser_version: Parser identity observed for the new revision.
        reason: Human-readable audit reason, bounded by the request model.
        changed_by: Stable operator/system identity.
        occurred_at: Aware event time used by the ledger CAS checks.

    Returns:
        One durable mutation result per affected fact, in fact-id order.

    Raises:
        ValueError: If identifiers, revision fields, or timestamps are invalid.
        ReviewedKnowledgeStoreError: If a concurrent state change prevents a
            CAS-bound mutation from being committed.
    """

    normalized_project = _require_identifier(project_id, "project_id")
    normalized_material = _require_identifier(material_id, "material_id")
    normalized_fingerprint = _require_source_fingerprint(source_fingerprint)
    normalized_source_version = str(source_version or "").strip()
    normalized_extractor_version = str(extractor_version or "").strip()
    normalized_parser_version = str(parser_version or "").strip()
    if not normalized_source_version or not normalized_extractor_version or not normalized_parser_version:
        raise ValueError("source revision versions must be non-empty")
    normalized_reason = str(reason or "").replace("\x00", "").strip()
    normalized_changed_by = _require_identifier(changed_by, "changed_by")
    normalized_time = _require_occurred_at(occurred_at)

    results: list[ReviewedKnowledgeMutationResult] = []
    facts = _fresh_facts_for_material(
        store,
        project_id=normalized_project,
        material_id=normalized_material,
    )
    for fact in sorted(facts, key=lambda item: item.fact_id):
        matching_provenance = tuple(
            provenance
            for provenance in fact.provenance
            if provenance.material_id == normalized_material
        )
        if not matching_provenance:
            continue
        if all(
            _matches_observed_revision(
                provenance,
                material_id=normalized_material,
                source_fingerprint=normalized_fingerprint,
                source_version=normalized_source_version,
                extractor_version=normalized_extractor_version,
                parser_version=normalized_parser_version,
            )
            for provenance in matching_provenance
        ):
            continue
        matching = next(
            provenance
            for provenance in matching_provenance
            if not _matches_observed_revision(
                provenance,
                material_id=normalized_material,
                source_fingerprint=normalized_fingerprint,
                source_version=normalized_source_version,
                extractor_version=normalized_extractor_version,
                parser_version=normalized_parser_version,
            )
        )
        observed = FactSourceRevision(
            material_id=normalized_material,
            source_fingerprint=normalized_fingerprint,
            source_version=normalized_source_version,
            extractor_version=normalized_extractor_version,
            parser_version=normalized_parser_version,
            locator=matching.locator,
        )
        request = ReviewedKnowledgeFreshnessRequest(
            operation_id=_stale_operation_id(
                project_id=normalized_project,
                material_id=normalized_material,
                fact_id=fact.fact_id,
                current_state_sha256=fact.state_sha256,
                source_fingerprint=normalized_fingerprint,
                source_version=normalized_source_version,
                extractor_version=normalized_extractor_version,
                parser_version=normalized_parser_version,
            ),
            project_id=normalized_project,
            fact_id=fact.fact_id,
            operation="mark_stale",
            expected_version=fact.version,
            expected_state_sha256=fact.state_sha256,
            observed_source_revision=observed,
            reason=normalized_reason,
            changed_by=normalized_changed_by,
            occurred_at=normalized_time,
        )
        results.append(store.transition_freshness(request))
    return tuple(results)


def mark_material_revision_changed(
    *,
    project_id: str,
    material_id: str,
    source_fingerprint: str,
    source_version: str,
    extractor_version: str,
    parser_version: str,
    reason: str,
    changed_by: str,
    occurred_at: datetime,
) -> tuple[ReviewedKnowledgeMutationResult, ...]:
    """Mark reviewed facts stale for an observed material revision.

    The caller supplies the complete, provenance-bound identity from the
    source-revision controller. A missing reviewed ledger is intentionally a
    no-op so ordinary projects do not gain an empty database as a side effect.
    """

    normalized_project = _require_identifier(project_id, "project_id")
    normalized_material = _require_identifier(material_id, "material_id")
    db_path: Path = project_data_path(
        normalized_project,
        "reviewed_knowledge",
        "reviewed_knowledge.db",
    )
    if not db_path.is_file() or db_path.stat().st_size <= 0:
        return ()
    return mark_material_facts_stale(
        store=ReviewedKnowledgeStore(db_path),
        project_id=normalized_project,
        material_id=normalized_material,
        source_fingerprint=source_fingerprint,
        source_version=source_version,
        extractor_version=extractor_version,
        parser_version=parser_version,
        reason=reason,
        changed_by=changed_by,
        occurred_at=occurred_at,
    )


def mark_material_deleted(
    *,
    project_id: str,
    material_id: str,
    occurred_at: datetime,
) -> tuple[ReviewedKnowledgeMutationResult, ...]:
    """Record stale receipts for reviewed facts before a material is deleted.

    Missing ledgers are a valid no-op for projects that have never promoted
    reviewed knowledge; this function never creates an empty database merely
    because a material was removed.
    """

    normalized_project = _require_identifier(project_id, "project_id")
    normalized_material = _require_identifier(material_id, "material_id")
    return mark_material_revision_changed(
        project_id=normalized_project,
        material_id=normalized_material,
        source_fingerprint=_deleted_source_fingerprint(
            normalized_project,
            normalized_material,
        ),
        source_version="deleted-v1",
        extractor_version="unavailable-v1",
        parser_version="unavailable-v1",
        reason="Source material was deleted; reviewed provenance requires revalidation.",
        changed_by="system:material-delete",
        occurred_at=occurred_at,
    )


__all__ = [
    "mark_material_revision_changed",
    "mark_material_deleted",
    "mark_material_facts_stale",
]
