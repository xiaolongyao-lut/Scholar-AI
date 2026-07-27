"""Strict durable contracts for citation parsing and candidate ``cites`` edges.

The records deliberately contain locators and fingerprints, never PDF pixels,
provider credentials, URLs used by model clients, or local filesystem paths.
Parsing outcomes and graph candidates are separate so an unmatched or failed
mention remains auditable without becoming a graph fact.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from literature_assistant.core.models.evidence import PdfBboxUnit, pdf_bbox_matches_unit

CITATION_MENTION_SCHEMA_VERSION: Literal["scholar-ai-citation-mention/v1"] = (
    "scholar-ai-citation-mention/v1"
)
CITES_CANDIDATE_SCHEMA_VERSION: Literal["scholar-ai-cites-candidate/v1"] = (
    "scholar-ai-cites-candidate/v1"
)

CitationOutcome = Literal["matched", "unmatched", "ambiguous", "over_limit", "failed"]
CitationMatchMethod = Literal["doi", "normalized_title", "author_year", "none"]
CitationUniqueMatchMethod = Literal["doi", "normalized_title", "author_year"]
CitationReviewStatus = Literal["candidate", "accepted", "rejected"]
CitationReviewDecisionStatus = Literal["accepted", "rejected"]
CitationFreshnessStatus = Literal["fresh", "stale"]
CitationCaptureStatus = Literal["scheduled", "succeeded", "failed"]

_OUTCOMES = frozenset({"matched", "unmatched", "ambiguous", "over_limit", "failed"})
_REVIEW_STATUSES = frozenset({"candidate", "accepted", "rejected"})
_FRESHNESS_STATUSES = frozenset({"fresh", "stale"})
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ABSOLUTE_LOCAL_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\[^\\\r\n]+\\|file://|"
    r"/(?:home|users|tmp|var|etc|mnt|volumes|private)(?:/|\b))",
    re.IGNORECASE,
)
_CREDENTIAL_RE = re.compile(
    r"(?:\b(?:authorization|api[-_ ]?key|access[-_ ]?token|refresh[-_ ]?token|"
    r"password|client[-_ ]?secret)\s*[:=]\s*\S+|"
    r"\bbearer\s+[A-Za-z0-9._=+/-]{8,})",
    re.IGNORECASE,
)
_PIXEL_PAYLOAD_RE = re.compile(r"\bdata:image/", re.IGNORECASE)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validator_field_name(info: ValidationInfo) -> str:
    field_name = info.field_name
    if field_name is None:
        raise RuntimeError("citation field validator requires a field name")
    return field_name


def _validate_identifier(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not _ID_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} has an unsupported identifier shape")
    return normalized


def _validate_optional_identifier(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _validate_identifier(value, field_name=field_name)


def _validate_safe_text(value: str, *, field_name: str) -> str:
    normalized = value.replace("\x00", "").strip()
    if _ABSOLUTE_LOCAL_PATH_RE.search(normalized):
        raise ValueError(f"{field_name} must not contain absolute local paths")
    if _CREDENTIAL_RE.search(normalized):
        raise ValueError(f"{field_name} must not contain credentials")
    if _PIXEL_PAYLOAD_RE.search(normalized):
        raise ValueError(f"{field_name} must not contain pixel payloads")
    return normalized


def _validate_fingerprint(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must use sha256:<64 lowercase hex>")
    return normalized


def _validate_bbox(value: object, *, field_name: str) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{field_name} must contain exactly four numbers")
    bbox: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{field_name} must contain exactly four finite numbers")
        number = float(item)
        if not math.isfinite(number):
            raise ValueError(f"{field_name} must contain exactly four finite numbers")
        bbox.append(number)
    return bbox


class CitationCaptureReceipt(BaseModel):
    """Durable status for one asynchronous local citation capture batch."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["scholar-ai-citation-capture-receipt/v1"] = (
        "scholar-ai-citation-capture-receipt/v1"
    )
    receipt_id: str = Field(min_length=1, max_length=256)
    project_id: str = Field(min_length=1, max_length=256)
    batch_id: str = Field(min_length=1, max_length=256)
    session_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=256)
    capture_sha256: str = Field(min_length=71, max_length=71)
    status: CitationCaptureStatus
    expected_mention_count: int = Field(ge=0, le=1_024)
    expected_candidate_count: int = Field(ge=0, le=1_024)
    stored_mention_count: int = Field(default=0, ge=0, le=1_024)
    stored_candidate_count: int = Field(default=0, ge=0, le=1_024)
    created_mention_count: int = Field(default=0, ge=0, le=1_024)
    created_candidate_count: int = Field(default=0, ge=0, le=1_024)
    reused_mention_count: int = Field(default=0, ge=0, le=1_024)
    reused_candidate_count: int = Field(default=0, ge=0, le=1_024)
    error_code: str | None = Field(default=None, min_length=1, max_length=96)
    scheduled_at: datetime
    completed_at: datetime | None = None

    @field_validator("receipt_id", "project_id", "batch_id", "session_id", "turn_id")
    @classmethod
    def _validate_ids(cls, value: str, info: ValidationInfo) -> str:
        return _validate_identifier(value, field_name=_validator_field_name(info))

    @field_validator("capture_sha256")
    @classmethod
    def _validate_capture_hash(cls, value: str) -> str:
        normalized = _validate_fingerprint(value, field_name="capture_sha256")
        if normalized is None:
            raise ValueError("capture_sha256 is required")
        return normalized

    @field_validator("error_code")
    @classmethod
    def _validate_error_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_:-]{0,95}", normalized):
            raise ValueError("error_code has an unsupported shape")
        return normalized

    @field_validator("scheduled_at", "completed_at")
    @classmethod
    def _validate_capture_time(
        cls,
        value: datetime | None,
        info: ValidationInfo,
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{info.field_name} must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _validate_capture_state(self) -> "CitationCaptureReceipt":
        if self.status == "scheduled":
            if self.completed_at is not None or self.error_code is not None:
                raise ValueError("scheduled capture receipts cannot be terminal")
            if any(
                (
                    self.stored_mention_count,
                    self.stored_candidate_count,
                    self.created_mention_count,
                    self.created_candidate_count,
                    self.reused_mention_count,
                    self.reused_candidate_count,
                )
            ):
                raise ValueError("scheduled capture receipts cannot report stored records")
        elif self.status == "succeeded":
            if self.completed_at is None or self.error_code is not None:
                raise ValueError("successful capture receipts require a clean completion")
            if self.stored_mention_count != self.expected_mention_count:
                raise ValueError("stored mention count must match the scheduled batch")
            if self.stored_candidate_count != self.expected_candidate_count:
                raise ValueError("stored candidate count must match the scheduled batch")
            if self.created_mention_count + self.reused_mention_count != self.stored_mention_count:
                raise ValueError("mention create/reuse counts must match stored mentions")
            if self.created_candidate_count + self.reused_candidate_count != self.stored_candidate_count:
                raise ValueError("candidate create/reuse counts must match stored candidates")
        else:
            if self.completed_at is None or self.error_code is None:
                raise ValueError("failed capture receipts require completion and an error code")
            if any(
                (
                    self.stored_mention_count,
                    self.stored_candidate_count,
                    self.created_mention_count,
                    self.created_candidate_count,
                    self.reused_mention_count,
                    self.reused_candidate_count,
                )
            ):
                raise ValueError("failed capture receipts cannot report partial records")
        if self.completed_at is not None and self.completed_at < self.scheduled_at:
            raise ValueError("capture completion cannot precede scheduling")
        return self


class _CitationRecordFields(BaseModel):
    """Shared immutable evidence fields copied from a mention to an edge."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_default=True)

    project_id: str = Field(min_length=1, max_length=256)
    batch_id: str = Field(min_length=1, max_length=256)
    session_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=256)
    selection_id: str | None = Field(default=None, max_length=256)
    source_material_id: str = Field(min_length=1, max_length=256)
    marker: str = Field(default="", max_length=512)
    outcome: CitationOutcome
    reason: str | None = Field(default=None, max_length=500)
    reference_text: str = Field(default="", max_length=12_000)

    source_page: int | None = Field(default=None, ge=1)
    source_chunk_id: str | None = Field(default=None, max_length=256)
    source_bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    source_bbox_unit: PdfBboxUnit | None = None
    reference_page: int | None = Field(default=None, ge=1)
    reference_number: int | None = Field(default=None, ge=1, le=9_999)
    reference_chunk_id: str | None = Field(default=None, max_length=256)
    reference_bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    reference_bbox_unit: PdfBboxUnit | None = None

    target_material_id: str | None = Field(default=None, max_length=256)
    target_material_title: str | None = Field(default=None, max_length=1_000)
    candidate_material_ids: list[str] = Field(default_factory=list, max_length=8)
    match_method: CitationMatchMethod = "none"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    source_version: str = Field(min_length=1, max_length=128)
    extractor_version: str = Field(min_length=1, max_length=128)
    parser_version: str = Field(min_length=1, max_length=128)
    resolver_version: str = Field(min_length=1, max_length=128)
    source_fingerprint: str = Field(min_length=71, max_length=71)
    reference_fingerprint: str | None = Field(default=None, min_length=71, max_length=71)
    target_fingerprint: str | None = Field(default=None, min_length=71, max_length=71)
    extractor_fingerprint: str | None = Field(default=None, min_length=71, max_length=71)
    parser_fingerprint: str | None = Field(default=None, min_length=71, max_length=71)
    resolver_fingerprint: str | None = Field(default=None, min_length=71, max_length=71)

    review_status: CitationReviewStatus = "candidate"
    freshness_status: CitationFreshnessStatus = "fresh"
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @field_validator(
        "project_id",
        "batch_id",
        "session_id",
        "turn_id",
        "source_material_id",
    )
    @classmethod
    def _validate_required_ids(cls, value: str, info: ValidationInfo) -> str:
        return _validate_identifier(value, field_name=_validator_field_name(info))

    @field_validator(
        "selection_id",
        "source_chunk_id",
        "reference_chunk_id",
        "target_material_id",
    )
    @classmethod
    def _validate_optional_ids(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _validate_optional_identifier(value, field_name=_validator_field_name(info))

    @field_validator("source_version", "extractor_version", "parser_version", "resolver_version")
    @classmethod
    def _validate_versions(cls, value: str, info: ValidationInfo) -> str:
        normalized = value.strip()
        if not _VERSION_RE.fullmatch(normalized):
            raise ValueError(f"{info.field_name} has an unsupported version shape")
        return normalized

    @field_validator(
        "source_fingerprint",
        "reference_fingerprint",
        "target_fingerprint",
        "extractor_fingerprint",
        "parser_fingerprint",
        "resolver_fingerprint",
    )
    @classmethod
    def _validate_fingerprints(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        return _validate_fingerprint(value, field_name=_validator_field_name(info))

    @field_validator("marker", "reference_text")
    @classmethod
    def _validate_durable_text(cls, value: str, info: ValidationInfo) -> str:
        return _validate_safe_text(value, field_name=_validator_field_name(info))

    @field_validator("reason", "target_material_title")
    @classmethod
    def _validate_optional_durable_text(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        if value is None:
            return None
        normalized = _validate_safe_text(value, field_name=_validator_field_name(info))
        return normalized or None

    @field_validator("source_bbox", "reference_bbox", mode="before")
    @classmethod
    def _validate_locator_bbox(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> list[float] | None:
        return _validate_bbox(value, field_name=_validator_field_name(info))

    @field_validator("candidate_material_ids", mode="before")
    @classmethod
    def _validate_candidate_material_ids(cls, value: object) -> list[str]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("candidate_material_ids must be a list")
        material_ids: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("candidate_material_ids must contain strings")
            material_id = _validate_identifier(item, field_name="candidate_material_ids")
            if material_id not in material_ids:
                material_ids.append(material_id)
        if len(material_ids) > 8:
            raise ValueError("candidate_material_ids accepts at most 8 values")
        return material_ids

    @field_validator("created_at", "updated_at")
    @classmethod
    def _require_aware_timestamp(cls, value: datetime, info: ValidationInfo) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{info.field_name} must include a timezone")
        return value

    @model_validator(mode="after")
    def _validate_shared_contract(self) -> "_CitationRecordFields":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.source_bbox is None:
            if self.source_bbox_unit is not None:
                raise ValueError("source_bbox_unit requires source_bbox")
        else:
            if self.source_page is None or self.source_bbox_unit is None:
                raise ValueError("source_bbox requires source_page and source_bbox_unit")
            if not pdf_bbox_matches_unit(self.source_bbox, self.source_bbox_unit):
                raise ValueError("source_bbox is outside the declared coordinate unit")
        if self.reference_bbox is None:
            if self.reference_bbox_unit is not None:
                raise ValueError("reference_bbox_unit requires reference_bbox")
        else:
            if self.reference_page is None or self.reference_bbox_unit is None:
                raise ValueError("reference_bbox requires reference_page and reference_bbox_unit")
            if not pdf_bbox_matches_unit(self.reference_bbox, self.reference_bbox_unit):
                raise ValueError("reference_bbox is outside the declared coordinate unit")
        if self.selection_id is None and self.source_page is None and self.source_chunk_id is None:
            raise ValueError("citation records require a source selection, page, or chunk locator")
        if self.marker == "" and self.outcome != "failed":
            raise ValueError("citation markers may be empty only for failed extraction")
        if self.source_material_id == self.target_material_id:
            raise ValueError("a citation target must differ from its source material")
        if len(self.candidate_material_ids) == 1:
            raise ValueError("ambiguous material evidence cannot contain only one candidate")
        if self.outcome == "ambiguous":
            if self.target_material_id in self.candidate_material_ids:
                raise ValueError("ambiguous citation mentions cannot select a target material")
        elif self.candidate_material_ids:
            raise ValueError("candidate_material_ids are only valid for ambiguous outcomes")

        target_fields_present = (
            any(
                value is not None
                for value in (
                    self.target_material_id,
                    self.target_material_title,
                    self.target_fingerprint,
                    self.confidence,
                )
            )
            or self.match_method != "none"
        )

        if self.outcome == "matched":
            if (
                self.target_material_id is None
                or self.match_method == "none"
                or self.confidence is None
                or not self.reference_text
                or self.reference_fingerprint is None
                or self.target_fingerprint is None
                or self.source_page is None
                or (self.reference_page is None and self.reference_chunk_id is None)
            ):
                raise ValueError(
                    "matched citation mentions require target identity, reference text, "
                    "source/reference locators, match method, confidence, and "
                    "reference/target fingerprints"
                )
        elif self.outcome == "over_limit":
            if not self.reason:
                raise ValueError("over_limit citation mentions require a reason")
            if target_fields_present and (
                self.target_material_id is None
                or self.match_method == "none"
                or self.confidence is None
                or self.target_fingerprint is None
                or not self.reference_text
                or self.reference_fingerprint is None
            ):
                raise ValueError("over_limit match evidence must be complete when present")
        else:
            if not self.reason:
                raise ValueError(f"{self.outcome} citation mentions require a reason")
            if target_fields_present:
                raise ValueError(f"{self.outcome} citation mentions must not carry match evidence")

        if self.review_status == "accepted" and self.outcome != "matched":
            raise ValueError("only matched citation records can be accepted")
        return self


class CitationMention(_CitationRecordFields):
    """One durable citation marker and its structured resolution outcome.

    ``outcome`` records matched, unmatched, ambiguous, over-limit, and failed
    results. Only a unique ``matched`` record may be projected to a
    :class:`CitesCandidate`; persistence alone never accepts the record.
    """

    schema_version: Literal["scholar-ai-citation-mention/v1"] = CITATION_MENTION_SCHEMA_VERSION
    mention_id: str = Field(min_length=1, max_length=256)

    @field_validator("mention_id")
    @classmethod
    def _validate_mention_id(cls, value: str) -> str:
        return _validate_identifier(value, field_name="mention_id")


class CitesCandidate(_CitationRecordFields):
    """One directed, reviewable source-material to target-material edge."""

    schema_version: Literal["scholar-ai-cites-candidate/v1"] = CITES_CANDIDATE_SCHEMA_VERSION
    candidate_id: str = Field(min_length=1, max_length=256)
    mention_id: str = Field(min_length=1, max_length=256)
    outcome: Literal["matched"] = "matched"
    reference_text: str = Field(min_length=1, max_length=12_000)
    source_page: int = Field(ge=1)
    target_material_id: str = Field(min_length=1, max_length=256)
    match_method: CitationUniqueMatchMethod
    confidence: float = Field(ge=0.0, le=1.0)
    reference_fingerprint: str = Field(min_length=71, max_length=71)
    target_fingerprint: str = Field(min_length=71, max_length=71)
    relation: Literal["cites"] = "cites"
    direction: Literal["directed"] = "directed"

    @field_validator("candidate_id", "mention_id")
    @classmethod
    def _validate_candidate_ids(cls, value: str, info: ValidationInfo) -> str:
        return _validate_identifier(value, field_name=_validator_field_name(info))


def cites_candidate_from_mention(
    mention: CitationMention,
    *,
    candidate_id: str,
) -> CitesCandidate:
    """Project one unique matched mention into a directed candidate edge.

    Args:
        mention: Valid durable mention with ``outcome == "matched"``.
        candidate_id: Stable caller-owned candidate identifier.

    Returns:
        A candidate carrying the same locator, provenance, and lifecycle axes.

    Raises:
        ValueError: If the mention is not a unique matched result.
    """

    if mention.outcome != "matched":
        raise ValueError("only matched citation mentions can create cites candidates")
    payload = mention.model_dump(
        mode="python",
        exclude={"schema_version", "mention_id"},
    )
    return CitesCandidate(
        candidate_id=candidate_id,
        mention_id=mention.mention_id,
        **payload,
    )


def citation_mention_dedupe_hash(mention: CitationMention) -> str:
    """Return the stable semantic hash used for mention idempotency.

    Caller-owned ids, lifecycle axes, and timestamps are excluded. The batch,
    source/parser versions, locators, match result, and fingerprints remain in
    the digest, so a materially different parse is retained as a new record.

    Args:
        mention: Validated citation mention to fingerprint.

    Returns:
        A lowercase ``sha256:<64 hex>`` semantic digest.
    """

    return _record_dedupe_hash(
        mention,
        excluded={
            "mention_id",
            "created_at",
            "updated_at",
            "review_status",
            "freshness_status",
        },
    )


def cites_candidate_dedupe_hash(candidate: CitesCandidate) -> str:
    """Return the stable semantic hash used for candidate idempotency.

    Args:
        candidate: Validated directed candidate to fingerprint.

    Returns:
        A lowercase ``sha256:<64 hex>`` semantic digest.
    """

    return _record_dedupe_hash(
        candidate,
        excluded={
            "candidate_id",
            "mention_id",
            "created_at",
            "updated_at",
            "review_status",
            "freshness_status",
        },
    )


def _record_dedupe_hash(record: BaseModel, *, excluded: set[str]) -> str:
    payload = record.model_dump(mode="json", exclude=excluded)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "CITATION_MENTION_SCHEMA_VERSION",
    "CITES_CANDIDATE_SCHEMA_VERSION",
    "CitationCaptureReceipt",
    "CitationCaptureStatus",
    "CitationFreshnessStatus",
    "CitationMatchMethod",
    "CitationMention",
    "CitationOutcome",
    "CitationReviewDecisionStatus",
    "CitationReviewStatus",
    "CitationUniqueMatchMethod",
    "CitesCandidate",
    "citation_mention_dedupe_hash",
    "cites_candidate_dedupe_hash",
    "cites_candidate_from_mention",
]
