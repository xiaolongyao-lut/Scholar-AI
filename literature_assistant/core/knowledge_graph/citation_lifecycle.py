"""Pure citation-candidate lifecycle contracts with no Wiki dependency."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from literature_assistant.core.knowledge_graph.citation_models import (
    CitationFreshnessStatus,
    CitationMention,
    CitationReviewDecisionStatus,
    CitationReviewStatus,
    CitesCandidate,
)

CitationLifecycleAxis = Literal["review", "freshness"]
CitationLifecycleStatus = Literal["candidate", "accepted", "rejected", "fresh", "stale"]
CitationSourceRevisionOperation = Literal["mark_stale", "revalidate"]
CitationSourceRevisionRole = Literal["source", "target"]
CitationSourceRevisionMismatch = Literal[
    "source_fingerprint",
    "source_version",
    "extractor_version",
    "parser_version",
    "target_fingerprint",
]

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVIEW_STATUSES = frozenset({"candidate", "accepted", "rejected"})
_REVIEW_TARGETS = frozenset({"accepted", "rejected"})
_FRESHNESS_STATUSES = frozenset({"fresh", "stale"})


class CitationSourceRevisionIdentity(BaseModel):
    """Caller-observed identity for one current project material revision."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    material_id: str = Field(min_length=1, max_length=256)
    source_fingerprint: str = Field(min_length=71, max_length=71)
    source_version: str = Field(min_length=1, max_length=128)
    extractor_version: str = Field(min_length=1, max_length=128)
    parser_version: str = Field(min_length=1, max_length=128)

    @field_validator("material_id")
    @classmethod
    def _validate_material_id(cls, value: str) -> str:
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("material_id has an unsupported identifier shape")
        return normalized

    @field_validator("source_fingerprint")
    @classmethod
    def _validate_source_fingerprint(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("source_fingerprint must use sha256:<64 lowercase hex>")
        return normalized

    @field_validator("source_version", "extractor_version", "parser_version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        normalized = value.strip()
        if not _VERSION_RE.fullmatch(normalized):
            raise ValueError("source revision versions have an unsupported shape")
        return normalized


class CitationSourceRevisionImpact(BaseModel):
    """One CAS-bound citation candidate selected by a source revision preflight."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1, max_length=256)
    mention_id: str = Field(min_length=1, max_length=256)
    material_role: CitationSourceRevisionRole
    mismatch_fields: tuple[CitationSourceRevisionMismatch, ...] = ()
    expected_freshness_status: CitationFreshnessStatus
    expected_updated_at: datetime

    @field_validator("candidate_id", "mention_id")
    @classmethod
    def _validate_record_id(cls, value: str) -> str:
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("citation source revision identifiers have an unsupported shape")
        return normalized

    @field_validator("mismatch_fields")
    @classmethod
    def _dedupe_mismatch_fields(
        cls,
        value: tuple[CitationSourceRevisionMismatch, ...],
    ) -> tuple[CitationSourceRevisionMismatch, ...]:
        if len(value) != len(set(value)):
            raise ValueError("mismatch_fields must not contain duplicates")
        return value

    @field_validator("expected_updated_at")
    @classmethod
    def _require_aware_updated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expected_updated_at must include a timezone")
        return value.astimezone(timezone.utc)


class CitationSourceRevisionPreflight(BaseModel):
    """Bounded read-only impact set whose digest is reused as apply CAS."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scholar-ai-citation-source-revision-preflight/v1"] = (
        "scholar-ai-citation-source-revision-preflight/v1"
    )
    project_id: str = Field(min_length=1, max_length=256)
    operation: CitationSourceRevisionOperation
    current_identity: CitationSourceRevisionIdentity
    impacts: tuple[CitationSourceRevisionImpact, ...]
    impact_fingerprint: str = Field(min_length=71, max_length=71)

    @field_validator("project_id")
    @classmethod
    def _validate_project_id(cls, value: str) -> str:
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("project_id has an unsupported identifier shape")
        return normalized

    @field_validator("impact_fingerprint")
    @classmethod
    def _validate_impact_fingerprint(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("impact_fingerprint must use sha256:<64 lowercase hex>")
        return normalized

    @model_validator(mode="after")
    def _validate_operation_impacts(self) -> "CitationSourceRevisionPreflight":
        if self.operation == "mark_stale":
            if any(
                impact.expected_freshness_status != "fresh" or not impact.mismatch_fields
                for impact in self.impacts
            ):
                raise ValueError("mark_stale impacts must be fresh and materially mismatched")
        elif any(impact.expected_freshness_status != "stale" for impact in self.impacts):
            raise ValueError("revalidate impacts must be stale")
        return self


class CitationSourceRevisionApplyReceipt(BaseModel):
    """Aggregate response backed by durable per-candidate lifecycle events."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scholar-ai-citation-source-revision-receipt/v1"] = (
        "scholar-ai-citation-source-revision-receipt/v1"
    )
    receipt_id: str = Field(min_length=1, max_length=256)
    project_id: str = Field(min_length=1, max_length=256)
    operation: CitationSourceRevisionOperation
    current_identity: CitationSourceRevisionIdentity
    impact_fingerprint: str = Field(min_length=71, max_length=71)
    candidate_ids: tuple[str, ...]
    events: tuple["CitationLifecycleEvent", ...]
    occurred_at: datetime


def citation_source_revision_impact_fingerprint(
    *,
    project_id: str,
    operation: CitationSourceRevisionOperation,
    current_identity: CitationSourceRevisionIdentity,
    impacts: tuple[CitationSourceRevisionImpact, ...],
) -> str:
    """Hash the complete caller-visible impact set used for apply CAS."""

    payload = {
        "project_id": project_id,
        "operation": operation,
        "current_identity": current_identity.model_dump(mode="json"),
        "impacts": [impact.model_dump(mode="json") for impact in impacts],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class CitationLifecycleEvent(BaseModel):
    """One durable audit event for a candidate lifecycle transition."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["scholar-ai-citation-lifecycle-event/v1"] = (
        "scholar-ai-citation-lifecycle-event/v1"
    )
    event_id: str = Field(min_length=1, max_length=256)
    candidate_id: str = Field(min_length=1, max_length=256)
    mention_id: str = Field(min_length=1, max_length=256)
    project_id: str = Field(min_length=1, max_length=256)
    batch_id: str = Field(min_length=1, max_length=256)
    axis: CitationLifecycleAxis
    from_status: CitationLifecycleStatus
    to_status: CitationLifecycleStatus
    reason: str = Field(min_length=1, max_length=2_000)
    changed_by: str = Field(min_length=1, max_length=256)
    occurred_at: datetime
    source_revision_receipt_id: str | None = Field(default=None, min_length=1, max_length=256)
    source_revision_operation: CitationSourceRevisionOperation | None = None
    source_revision_identity: CitationSourceRevisionIdentity | None = None
    source_revision_impact_fingerprint: str | None = Field(
        default=None,
        min_length=71,
        max_length=71,
    )

    @field_validator(
        "event_id",
        "candidate_id",
        "mention_id",
        "project_id",
        "batch_id",
        "changed_by",
    )
    @classmethod
    def _validate_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("citation lifecycle identifiers have an unsupported shape")
        return normalized

    @field_validator("source_revision_receipt_id")
    @classmethod
    def _validate_optional_receipt_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("source revision receipt id has an unsupported shape")
        return normalized

    @field_validator("source_revision_impact_fingerprint")
    @classmethod
    def _validate_optional_impact_fingerprint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("source revision impact fingerprint must use sha256:<64 lowercase hex>")
        return normalized

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        normalized = value.replace("\x00", "").strip()
        if not normalized:
            raise ValueError("reason cannot be empty")
        return normalized

    @field_validator("occurred_at")
    @classmethod
    def _require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_axis_statuses(self) -> "CitationLifecycleEvent":
        if self.axis == "review":
            if self.from_status not in _REVIEW_STATUSES or self.to_status not in _REVIEW_TARGETS:
                raise ValueError("review lifecycle events require citation review statuses")
            if self.from_status != "candidate":
                raise ValueError("review lifecycle events must start from candidate")
        elif self.from_status not in _FRESHNESS_STATUSES or self.to_status not in _FRESHNESS_STATUSES:
            raise ValueError("freshness lifecycle events require citation freshness statuses")
        if self.from_status == self.to_status:
            raise ValueError("citation lifecycle events require a real status change")
        source_revision_fields = (
            self.source_revision_receipt_id,
            self.source_revision_operation,
            self.source_revision_identity,
            self.source_revision_impact_fingerprint,
        )
        if any(value is not None for value in source_revision_fields):
            if any(value is None for value in source_revision_fields):
                raise ValueError("source revision lifecycle metadata must be complete")
            if self.axis != "freshness":
                raise ValueError("source revision metadata is only valid for freshness events")
            expected_target = (
                "stale" if self.source_revision_operation == "mark_stale" else "fresh"
            )
            if self.to_status != expected_target:
                raise ValueError("source revision operation does not match lifecycle target")
        return self


@dataclass(frozen=True, slots=True)
class CitationLifecycleTransitionResult:
    """Canonical candidate, mention, and audit event committed together."""

    candidate: CitesCandidate
    mention: CitationMention
    event: CitationLifecycleEvent


def require_review_transition(
    current: CitationReviewStatus,
    target: CitationReviewDecisionStatus,
) -> None:
    """Require the one-way candidate review state machine.

    Args:
        current: Persisted candidate review status.
        target: Explicit human review decision.

    Raises:
        ValueError: If the decision is not ``candidate -> accepted|rejected``.
    """

    if current != "candidate":
        raise ValueError("review transitions require candidate as the current status")
    if target not in _REVIEW_TARGETS:
        raise ValueError("review target_status must be accepted or rejected")


def require_freshness_transition(
    current: CitationFreshnessStatus,
    target: CitationFreshnessStatus,
) -> None:
    """Require a real transition between fresh and stale.

    Args:
        current: Persisted candidate freshness status.
        target: Explicit stale or revalidated-fresh target.

    Raises:
        ValueError: If either status is unsupported or no change is requested.
    """

    if current not in _FRESHNESS_STATUSES or target not in _FRESHNESS_STATUSES:
        raise ValueError("freshness statuses must be fresh or stale")
    if current == target:
        raise ValueError("freshness transitions require a real status change")


def make_lifecycle_event(
    *,
    candidate: CitesCandidate,
    axis: CitationLifecycleAxis,
    from_status: CitationLifecycleStatus,
    to_status: CitationLifecycleStatus,
    reason: str,
    changed_by: str,
    occurred_at: datetime,
    source_revision_receipt_id: str | None = None,
    source_revision_operation: CitationSourceRevisionOperation | None = None,
    source_revision_identity: CitationSourceRevisionIdentity | None = None,
    source_revision_impact_fingerprint: str | None = None,
) -> CitationLifecycleEvent:
    """Build a validated audit event from the canonical candidate identity.

    Args:
        candidate: Updated canonical candidate that owns the event.
        axis: Lifecycle axis changed by the transaction.
        from_status: Persisted status observed before the change.
        to_status: Status committed by the change.
        reason: Non-empty human or system audit reason.
        changed_by: Stable local actor identifier.
        occurred_at: Aware timestamp shared by records and event.

    Returns:
        Strict event ready for durable persistence.
    """

    return CitationLifecycleEvent(
        event_id=f"citation-transition-{uuid4().hex}",
        candidate_id=candidate.candidate_id,
        mention_id=candidate.mention_id,
        project_id=candidate.project_id,
        batch_id=candidate.batch_id,
        axis=axis,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        changed_by=changed_by,
        occurred_at=occurred_at,
        source_revision_receipt_id=source_revision_receipt_id,
        source_revision_operation=source_revision_operation,
        source_revision_identity=source_revision_identity,
        source_revision_impact_fingerprint=source_revision_impact_fingerprint,
    )


__all__ = [
    "CitationLifecycleAxis",
    "CitationLifecycleEvent",
    "CitationLifecycleStatus",
    "CitationLifecycleTransitionResult",
    "CitationSourceRevisionApplyReceipt",
    "CitationSourceRevisionIdentity",
    "CitationSourceRevisionImpact",
    "CitationSourceRevisionOperation",
    "CitationSourceRevisionPreflight",
    "CitationSourceRevisionRole",
    "citation_source_revision_impact_fingerprint",
    "make_lifecycle_event",
    "require_freshness_transition",
    "require_review_transition",
]
