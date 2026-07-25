"""Strict contracts for explicitly promoted, reviewed graph knowledge."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ReviewedCandidateKind = Literal[
    "citation",
    "visual_observation",
    "graph_relation",
    "wiki_review",
    "annotation",
]
ReviewedKnowledgeFreshness = Literal["fresh", "stale"]
ReviewedKnowledgeAvailability = Literal["active", "withdrawn"]
ReviewedKnowledgeOperation = Literal["promote", "mark_stale", "revalidate", "withdraw"]
ReviewedKnowledgeOutcome = Literal[
    "created",
    "revised",
    "stale",
    "revalidated",
    "withdrawn",
]

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_PREDICATE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]{0,127}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _clean_text(value: str, field_name: str) -> str:
    normalized = value.replace("\x00", "").strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(timezone.utc)


class AcceptedCandidateReview(BaseModel):
    """External evidence that a typed candidate was explicitly accepted."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    project_id: str = Field(min_length=1, max_length=256)
    target_kind: ReviewedCandidateKind
    candidate_id: str = Field(min_length=1, max_length=256)
    decision: Literal["accepted"] = "accepted"
    decision_receipt_id: str = Field(min_length=1, max_length=256)
    decided_by: str = Field(min_length=1, max_length=256)
    decided_at: datetime

    @field_validator(
        "project_id",
        "candidate_id",
        "decision_receipt_id",
        "decided_by",
    )
    @classmethod
    def _validate_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("review identifiers have an unsupported shape")
        return normalized

    @field_validator("decided_at")
    @classmethod
    def _validate_decided_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "decided_at")


class FactSourceRevision(BaseModel):
    """One provenance locator bound to an exact source and parser identity."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    material_id: str = Field(min_length=1, max_length=256)
    source_fingerprint: str = Field(min_length=71, max_length=71)
    source_version: str = Field(min_length=1, max_length=128)
    extractor_version: str = Field(min_length=1, max_length=128)
    parser_version: str = Field(min_length=1, max_length=128)
    locator: str = Field(min_length=1, max_length=2_048)

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

    @field_validator("locator")
    @classmethod
    def _validate_locator(cls, value: str) -> str:
        return _clean_text(value, "locator")

    def identity_tuple(self) -> tuple[str, str, str, str, str]:
        """Return fields that define the material revision, excluding its locator."""

        return (
            self.material_id,
            self.source_fingerprint,
            self.source_version,
            self.extractor_version,
            self.parser_version,
        )


def accepted_graph_fact_content_hash(
    *,
    project_id: str,
    fact_id: str,
    subject_ref: str,
    predicate: str,
    object_ref: str,
    statement: str,
    provenance: tuple[FactSourceRevision, ...],
) -> str:
    """Return the stable semantic-and-provenance hash for one fact revision."""

    return _canonical_sha256(
        {
            "fact_id": fact_id,
            "object_ref": object_ref,
            "predicate": predicate,
            "project_id": project_id,
            "provenance": [item.model_dump(mode="json") for item in provenance],
            "statement": statement,
            "subject_ref": subject_ref,
        }
    )


def accepted_graph_fact_state_hash(
    *,
    project_id: str,
    fact_id: str,
    version: int,
    freshness_status: ReviewedKnowledgeFreshness,
    availability_status: ReviewedKnowledgeAvailability,
    content_sha256: str,
    accepted_review: AcceptedCandidateReview,
    stale_source_revision: FactSourceRevision | None,
) -> str:
    """Return a CAS hash over all mutable current-state fields."""

    return _canonical_sha256(
        {
            "accepted_review": accepted_review.model_dump(mode="json"),
            "content_sha256": content_sha256,
            "fact_id": fact_id,
            "freshness_status": freshness_status,
            "availability_status": availability_status,
            "project_id": project_id,
            "stale_source_revision": (
                stale_source_revision.model_dump(mode="json")
                if stale_source_revision is not None
                else None
            ),
            "version": version,
        }
    )


class AcceptedGraphFact(BaseModel):
    """Canonical reviewed fact owned by the independent knowledge ledger."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["scholar-ai-accepted-graph-fact/v1"] = (
        "scholar-ai-accepted-graph-fact/v1"
    )
    project_id: str = Field(min_length=1, max_length=256)
    fact_id: str = Field(min_length=1, max_length=256)
    subject_ref: str = Field(min_length=1, max_length=1_024)
    predicate: str = Field(min_length=1, max_length=128)
    object_ref: str = Field(min_length=1, max_length=1_024)
    statement: str = Field(min_length=1, max_length=8_000)
    provenance: tuple[FactSourceRevision, ...] = Field(min_length=1, max_length=64)
    accepted_review: AcceptedCandidateReview
    freshness_status: ReviewedKnowledgeFreshness = "fresh"
    availability_status: ReviewedKnowledgeAvailability = "active"
    stale_source_revision: FactSourceRevision | None = None
    version: int = Field(ge=1)
    content_sha256: str = Field(min_length=71, max_length=71)
    state_sha256: str = Field(min_length=71, max_length=71)
    created_at: datetime
    updated_at: datetime

    @field_validator("project_id", "fact_id")
    @classmethod
    def _validate_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("fact identifiers have an unsupported shape")
        return normalized

    @field_validator("predicate")
    @classmethod
    def _validate_predicate(cls, value: str) -> str:
        normalized = value.strip()
        if not _PREDICATE_RE.fullmatch(normalized):
            raise ValueError("predicate has an unsupported relation shape")
        return normalized

    @field_validator("subject_ref", "object_ref", "statement")
    @classmethod
    def _validate_fact_text(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "fact text")
        return _clean_text(value, str(field_name))

    @field_validator("provenance")
    @classmethod
    def _validate_provenance(
        cls,
        value: tuple[FactSourceRevision, ...],
    ) -> tuple[FactSourceRevision, ...]:
        keys = tuple((item.material_id, item.locator) for item in value)
        if len(keys) != len(set(keys)):
            raise ValueError("provenance must not repeat a material locator")
        return value

    @field_validator("content_sha256", "state_sha256")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("fact hashes must use sha256:<64 lowercase hex>")
        return normalized

    @field_validator("created_at", "updated_at")
    @classmethod
    def _validate_timestamp(cls, value: datetime, info: object) -> datetime:
        field_name = getattr(info, "field_name", "timestamp")
        return _aware_utc(value, str(field_name))

    @model_validator(mode="after")
    def _validate_consistency(self) -> "AcceptedGraphFact":
        if self.accepted_review.project_id != self.project_id:
            raise ValueError("accepted review must belong to the fact project")
        if self.accepted_review.decided_at > self.updated_at:
            raise ValueError("accepted review cannot postdate the fact revision")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.freshness_status == "fresh" and self.stale_source_revision is not None:
            raise ValueError("fresh facts cannot retain stale source evidence")
        if self.freshness_status == "stale" and self.stale_source_revision is None:
            raise ValueError("stale facts require observed source revision evidence")
        expected_content_hash = accepted_graph_fact_content_hash(
            project_id=self.project_id,
            fact_id=self.fact_id,
            subject_ref=self.subject_ref,
            predicate=self.predicate,
            object_ref=self.object_ref,
            statement=self.statement,
            provenance=self.provenance,
        )
        if self.content_sha256 != expected_content_hash:
            raise ValueError("content_sha256 does not match fact content")
        expected_state_hash = accepted_graph_fact_state_hash(
            project_id=self.project_id,
            fact_id=self.fact_id,
            version=self.version,
            freshness_status=self.freshness_status,
            availability_status=self.availability_status,
            content_sha256=self.content_sha256,
            accepted_review=self.accepted_review,
            stale_source_revision=self.stale_source_revision,
        )
        if self.state_sha256 != expected_state_hash:
            raise ValueError("state_sha256 does not match fact state")
        return self


class PromoteAcceptedGraphFactRequest(BaseModel):
    """Explicit, idempotent promotion request with current-state CAS."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["scholar-ai-promote-accepted-graph-fact-request/v1"] = (
        "scholar-ai-promote-accepted-graph-fact-request/v1"
    )
    operation_id: str = Field(min_length=1, max_length=256)
    project_id: str = Field(min_length=1, max_length=256)
    fact_id: str = Field(min_length=1, max_length=256)
    expected_version: int = Field(ge=0)
    expected_state_sha256: str | None = Field(
        default=None, min_length=71, max_length=71
    )
    subject_ref: str = Field(min_length=1, max_length=1_024)
    predicate: str = Field(min_length=1, max_length=128)
    object_ref: str = Field(min_length=1, max_length=1_024)
    statement: str = Field(min_length=1, max_length=8_000)
    provenance: tuple[FactSourceRevision, ...] = Field(min_length=1, max_length=64)
    accepted_review: AcceptedCandidateReview
    reason: str = Field(min_length=1, max_length=2_000)
    requested_by: str = Field(min_length=1, max_length=256)
    requested_at: datetime

    @field_validator("operation_id", "project_id", "fact_id", "requested_by")
    @classmethod
    def _validate_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("promotion identifiers have an unsupported shape")
        return normalized

    @field_validator("predicate")
    @classmethod
    def _validate_predicate(cls, value: str) -> str:
        normalized = value.strip()
        if not _PREDICATE_RE.fullmatch(normalized):
            raise ValueError("predicate has an unsupported relation shape")
        return normalized

    @field_validator("subject_ref", "object_ref", "statement", "reason")
    @classmethod
    def _validate_text(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "promotion text")
        return _clean_text(value, str(field_name))

    @field_validator("provenance")
    @classmethod
    def _validate_provenance(
        cls,
        value: tuple[FactSourceRevision, ...],
    ) -> tuple[FactSourceRevision, ...]:
        keys = tuple((item.material_id, item.locator) for item in value)
        if len(keys) != len(set(keys)):
            raise ValueError("provenance must not repeat a material locator")
        return value

    @field_validator("expected_state_sha256")
    @classmethod
    def _validate_expected_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("expected_state_sha256 must use sha256:<64 lowercase hex>")
        return normalized

    @field_validator("requested_at")
    @classmethod
    def _validate_requested_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "requested_at")

    @model_validator(mode="after")
    def _validate_cas_and_review(self) -> "PromoteAcceptedGraphFactRequest":
        if self.expected_version == 0 and self.expected_state_sha256 is not None:
            raise ValueError("new fact promotion cannot include an expected state hash")
        if self.expected_version > 0 and self.expected_state_sha256 is None:
            raise ValueError("fact revision promotion requires an expected state hash")
        if self.accepted_review.project_id != self.project_id:
            raise ValueError("accepted review must belong to the promotion project")
        if self.accepted_review.decided_at > self.requested_at:
            raise ValueError("accepted review cannot postdate the promotion request")
        return self


class ReviewedKnowledgeFreshnessRequest(BaseModel):
    """Explicit stale or revalidate request bound to one current fact state."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["scholar-ai-reviewed-knowledge-freshness-request/v1"] = (
        "scholar-ai-reviewed-knowledge-freshness-request/v1"
    )
    operation_id: str = Field(min_length=1, max_length=256)
    project_id: str = Field(min_length=1, max_length=256)
    fact_id: str = Field(min_length=1, max_length=256)
    operation: Literal["mark_stale", "revalidate"]
    expected_version: int = Field(ge=1)
    expected_state_sha256: str = Field(min_length=71, max_length=71)
    observed_source_revision: FactSourceRevision | None = None
    validated_provenance: tuple[FactSourceRevision, ...] = Field(
        default=(), max_length=64
    )
    reason: str = Field(min_length=1, max_length=2_000)
    changed_by: str = Field(min_length=1, max_length=256)
    occurred_at: datetime

    @field_validator("operation_id", "project_id", "fact_id", "changed_by")
    @classmethod
    def _validate_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("freshness identifiers have an unsupported shape")
        return normalized

    @field_validator("expected_state_sha256")
    @classmethod
    def _validate_expected_hash(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("expected_state_sha256 must use sha256:<64 lowercase hex>")
        return normalized

    @field_validator("validated_provenance")
    @classmethod
    def _validate_provenance(
        cls,
        value: tuple[FactSourceRevision, ...],
    ) -> tuple[FactSourceRevision, ...]:
        keys = tuple((item.material_id, item.locator) for item in value)
        if len(keys) != len(set(keys)):
            raise ValueError("validated provenance must not repeat a material locator")
        return value

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _clean_text(value, "reason")

    @field_validator("occurred_at")
    @classmethod
    def _validate_occurred_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "occurred_at")

    @model_validator(mode="after")
    def _validate_operation_evidence(self) -> "ReviewedKnowledgeFreshnessRequest":
        if self.operation == "mark_stale":
            if self.observed_source_revision is None or self.validated_provenance:
                raise ValueError(
                    "mark_stale requires one observed revision and no validated provenance"
                )
        elif self.observed_source_revision is not None or not self.validated_provenance:
            raise ValueError(
                "revalidate requires validated provenance and no observed revision"
            )
        return self


class WithdrawAcceptedGraphFactRequest(BaseModel):
    """Explicit withdrawal request bound to one current fact state."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["scholar-ai-withdraw-accepted-graph-fact-request/v1"] = (
        "scholar-ai-withdraw-accepted-graph-fact-request/v1"
    )
    operation_id: str = Field(min_length=1, max_length=256)
    project_id: str = Field(min_length=1, max_length=256)
    fact_id: str = Field(min_length=1, max_length=256)
    expected_version: int = Field(ge=1)
    expected_state_sha256: str = Field(min_length=71, max_length=71)
    reason: str = Field(min_length=1, max_length=2_000)
    changed_by: str = Field(min_length=1, max_length=256)
    occurred_at: datetime

    @field_validator("operation_id", "project_id", "fact_id", "changed_by")
    @classmethod
    def _validate_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("withdraw identifiers have an unsupported shape")
        return normalized

    @field_validator("expected_state_sha256")
    @classmethod
    def _validate_expected_hash(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("expected_state_sha256 must use sha256:<64 lowercase hex>")
        return normalized

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _clean_text(value, "reason")

    @field_validator("occurred_at")
    @classmethod
    def _validate_occurred_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "occurred_at")


class ReviewedKnowledgeReceipt(BaseModel):
    """Durable receipt for one explicit reviewed-knowledge mutation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["scholar-ai-reviewed-knowledge-receipt/v1"] = (
        "scholar-ai-reviewed-knowledge-receipt/v1"
    )
    receipt_id: str = Field(min_length=1, max_length=256)
    operation_id: str = Field(min_length=1, max_length=256)
    request_sha256: str = Field(min_length=71, max_length=71)
    project_id: str = Field(min_length=1, max_length=256)
    fact_id: str = Field(min_length=1, max_length=256)
    operation: ReviewedKnowledgeOperation
    outcome: ReviewedKnowledgeOutcome
    previous_version: int = Field(ge=0)
    result_version: int = Field(ge=1)
    previous_state_sha256: str | None = Field(
        default=None, min_length=71, max_length=71
    )
    result_state_sha256: str = Field(min_length=71, max_length=71)
    accepted_review: AcceptedCandidateReview | None = None
    observed_source_revision: FactSourceRevision | None = None
    validated_provenance: tuple[FactSourceRevision, ...] = Field(
        default=(), max_length=64
    )
    reason: str = Field(min_length=1, max_length=2_000)
    changed_by: str = Field(min_length=1, max_length=256)
    occurred_at: datetime

    @field_validator(
        "receipt_id",
        "operation_id",
        "project_id",
        "fact_id",
        "changed_by",
    )
    @classmethod
    def _validate_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("receipt identifiers have an unsupported shape")
        return normalized

    @field_validator("request_sha256", "previous_state_sha256", "result_state_sha256")
    @classmethod
    def _validate_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("receipt hashes must use sha256:<64 lowercase hex>")
        return normalized

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _clean_text(value, "reason")

    @field_validator("occurred_at")
    @classmethod
    def _validate_occurred_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "occurred_at")

    @model_validator(mode="after")
    def _validate_operation_shape(self) -> "ReviewedKnowledgeReceipt":
        if self.result_version != self.previous_version + 1:
            raise ValueError(
                "receipt versions must describe exactly one committed revision"
            )
        if (self.previous_version == 0) != (self.previous_state_sha256 is None):
            raise ValueError("only fact creation can omit the previous state hash")
        if self.operation == "promote":
            expected_outcome = "created" if self.previous_version == 0 else "revised"
            if self.outcome != expected_outcome:
                raise ValueError("promotion outcome does not match previous fact state")
            if (
                self.accepted_review is None
                or self.observed_source_revision is not None
                or self.validated_provenance
            ):
                raise ValueError("promotion receipt evidence is incomplete or mixed")
        elif self.operation == "mark_stale":
            if (
                self.outcome != "stale"
                or self.accepted_review is not None
                or self.observed_source_revision is None
                or self.validated_provenance
            ):
                raise ValueError("stale receipt evidence is incomplete or mixed")
        elif self.operation == "revalidate":
            if (
                self.outcome != "revalidated"
                or self.accepted_review is not None
                or self.observed_source_revision is not None
                or not self.validated_provenance
            ):
                raise ValueError("revalidate receipt evidence is incomplete or mixed")
        elif (
            self.outcome != "withdrawn"
            or self.accepted_review is not None
            or self.observed_source_revision is not None
            or self.validated_provenance
        ):
            raise ValueError(
                "withdraw receipt cannot contain promotion or revision evidence"
            )
        return self


@dataclass(frozen=True, slots=True)
class ReviewedKnowledgeMutationResult:
    """Historical fact revision, durable receipt, and replay indicator."""

    fact: AcceptedGraphFact
    receipt: ReviewedKnowledgeReceipt
    replayed: bool


def reviewed_knowledge_request_hash(
    request: (
        PromoteAcceptedGraphFactRequest
        | ReviewedKnowledgeFreshnessRequest
        | WithdrawAcceptedGraphFactRequest
    ),
) -> str:
    """Hash the complete validated request for durable idempotency checks."""

    if not isinstance(
        request,
        (
            PromoteAcceptedGraphFactRequest,
            ReviewedKnowledgeFreshnessRequest,
            WithdrawAcceptedGraphFactRequest,
        ),
    ):
        raise TypeError("request must be a reviewed-knowledge mutation request")
    return _canonical_sha256(request.model_dump(mode="json"))


__all__ = [
    "AcceptedCandidateReview",
    "AcceptedGraphFact",
    "FactSourceRevision",
    "PromoteAcceptedGraphFactRequest",
    "ReviewedCandidateKind",
    "ReviewedKnowledgeAvailability",
    "ReviewedKnowledgeFreshness",
    "ReviewedKnowledgeFreshnessRequest",
    "ReviewedKnowledgeMutationResult",
    "ReviewedKnowledgeOperation",
    "ReviewedKnowledgeOutcome",
    "ReviewedKnowledgeReceipt",
    "WithdrawAcceptedGraphFactRequest",
    "accepted_graph_fact_content_hash",
    "accepted_graph_fact_state_hash",
    "reviewed_knowledge_request_hash",
]
