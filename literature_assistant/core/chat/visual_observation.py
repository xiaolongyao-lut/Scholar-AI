"""Typed, pixel-free visual observation records for SmartRead history."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


VISUAL_OBSERVATION_SCHEMA_VERSION = "scholar-ai-visual-observation/v1"
VISUAL_OBSERVATION_REF_SCHEMA_VERSION = "scholar-ai-visual-observation-ref/v1"
VISUAL_OBSERVATION_MAX_COUNT = 12

VisualObservationRoute = Literal["direct_model", "vision_aux_mcp"]
VisualObservationOutputScope = Literal["answer_joint", "image_note"]
VisualObservationGenerationStatus = Literal["succeeded", "failed"]
VisualObservationReviewStatus = Literal["candidate", "accepted", "rejected", "withdrawn"]
VisualObservationReviewDecisionStatus = Literal["accepted", "rejected", "withdrawn"]
VisualObservationReferenceReviewStatus = Literal[
    "candidate",
    "accepted",
    "rejected",
    "withdrawn",
    "stale",
]
VisualObservationFreshnessStatus = Literal["fresh", "stale"]
VisualObservationCacheStatus = Literal["hit", "miss", "bypassed", "unavailable"]
VisualObservationLifecycleAxis = Literal["review", "freshness"]
VisualObservationLifecycleStatus = Literal[
    "candidate",
    "accepted",
    "rejected",
    "withdrawn",
    "fresh",
    "stale",
]
VisualObservationSourceRevisionOperation = Literal["mark_stale", "revalidate"]

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_PRODUCER_URI_RE = re.compile(
    r"^(?:[A-Za-z][A-Za-z0-9+.-]*://|file:|data:)",
    re.IGNORECASE,
)
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_SENSITIVE_PRODUCER_TEXT_RE = re.compile(
    r"(?:base[_-]?url|authorization|api[_-]?key|access[_-]?token|"
    r"bearer(?:\s|$)|client[_-]?secret|private[_-]?key)",
    re.IGNORECASE,
)
_SECRET_LIKE_RE = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]{16,}|\bAIza[0-9A-Za-z_-]{20,}|\bxox[baprs]-[0-9A-Za-z-]{10,})"
)
_UNSAFE_DURABLE_TEXT_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|(?:https?|file|data)://|authorization|api[_-]?key|"
    r"access[_-]?token|bearer\s|client[_-]?secret|private[_-]?key)",
    re.IGNORECASE,
)
_ERROR_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
_ALLOWED_MIME = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
_REVIEW_STATUSES = frozenset({"candidate", "accepted", "rejected", "withdrawn"})
_REVIEW_TARGETS = frozenset({"accepted", "rejected", "withdrawn"})
_FRESHNESS_STATUSES = frozenset({"fresh", "stale"})


def _trimmed(value: object, *, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized[:max_length] or None


def _aware_utc(value: datetime, field_name: str) -> datetime:
    """Return a timezone-aware timestamp normalized to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(timezone.utc)


def _validated_audit_text(value: str, field_name: str) -> str:
    """Normalize bounded audit text while rejecting secret-like content."""

    normalized = value.replace("\x00", "").strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if _SECRET_LIKE_RE.search(normalized) or _SENSITIVE_PRODUCER_TEXT_RE.search(normalized):
        raise ValueError(f"{field_name} contains sensitive-looking content")
    return normalized


def _canonical_sha256(value: object) -> str:
    """Hash one validated JSON-compatible value with stable encoding."""

    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def visual_material_source_binding_fingerprint(
    *,
    project_id: str,
    material_id: str,
    raw_source_sha256: str,
) -> str:
    """Return a material-specific visual source binding fingerprint.

    Raw source SHA values are retained separately on candidates. This derived
    binding prevents two material records containing identical PDF bytes from
    sharing a stale transition merely because they have the same content hash.

    Args:
        project_id: Owning project identifier.
        material_id: Owning material identifier.
        raw_source_sha256: Exact raw source content fingerprint.

    Returns:
        Deterministic material-specific SHA-256 binding.
    """

    normalized_project = str(project_id or "").strip()
    normalized_material = str(material_id or "").strip()
    normalized_source = str(raw_source_sha256 or "").strip().lower()
    if not _ID_RE.fullmatch(normalized_project):
        raise ValueError("project_id has an unsupported identifier shape")
    if not _ID_RE.fullmatch(normalized_material):
        raise ValueError("material_id has an unsupported identifier shape")
    if not _SHA256_RE.fullmatch(normalized_source):
        raise ValueError("raw_source_sha256 must use sha256:<64 lowercase hex>")
    return _canonical_sha256(
        {
            "schema_version": "scholar-ai-visual-material-source-binding/v1",
            "project_id": normalized_project,
            "material_id": normalized_material,
            "raw_source_sha256": normalized_source,
        }
    )


def _allowlisted_mapping(value: object, keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {key: value[key] for key in keys if key in value}


def _safe_relative_artifact_ref(value: object) -> str | None:
    normalized = _trimmed(value, max_length=500)
    if (
        normalized is None
        or normalized.startswith(("/", "\\"))
        or "\\" in normalized
        or ":" in normalized
        or _WINDOWS_DRIVE_RE.match(normalized)
        or _URI_SCHEME_RE.match(normalized)
    ):
        return None
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.as_posix()


def _safe_producer_text(value: object, *, max_length: int) -> str | None:
    """Return bounded producer identity text without endpoints or credentials."""

    normalized = _trimmed(value, max_length=max_length)
    if normalized is None:
        return None
    if (
        normalized.startswith(("/", "\\"))
        or "\\" in normalized
        or _WINDOWS_DRIVE_RE.match(normalized)
        or _PRODUCER_URI_RE.match(normalized)
        or _SENSITIVE_PRODUCER_TEXT_RE.search(normalized)
        or _SECRET_LIKE_RE.search(normalized)
    ):
        return None
    return normalized


class VisualObservationError(BaseModel):
    """Sanitized failure metadata safe for durable local history."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=96)
    message: str = Field(min_length=1, max_length=500)
    recoverable: bool = True

    @field_validator("code", mode="before")
    @classmethod
    def _normalize_code(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not _ERROR_CODE_RE.fullmatch(normalized):
            raise ValueError("visual observation error code has an unsupported shape")
        return normalized

    @field_validator("message", mode="before")
    @classmethod
    def _normalize_message(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.replace("\x00", "").strip()
        if _UNSAFE_DURABLE_TEXT_RE.search(normalized) or _SECRET_LIKE_RE.search(normalized):
            return "Visual observation failure details were redacted."
        return normalized


class VisualObservationImageInput(BaseModel):
    """One image identity without pixels, request indexes, or private paths."""

    model_config = ConfigDict(extra="forbid")

    image_id: str = Field(min_length=1, max_length=128)
    content_sha256: str = Field(min_length=71, max_length=71)
    mime: str = Field(min_length=1, max_length=32)
    size: int = Field(ge=1, le=32 * 1024 * 1024)
    selection_ids: list[str] = Field(default_factory=list, max_length=VISUAL_OBSERVATION_MAX_COUNT)
    derived_artifact_ref: str | None = Field(default=None, max_length=500)
    artifact_sha256: str | None = Field(default=None, min_length=71, max_length=71)

    @field_validator("image_id")
    @classmethod
    def _validate_image_id(cls, value: str) -> str:
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("image_id has an unsupported shape")
        return normalized

    @field_validator("content_sha256", "artifact_sha256")
    @classmethod
    def _validate_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("visual image hashes must be sha256:<64 lowercase hex>")
        return normalized

    @field_validator("mime")
    @classmethod
    def _validate_mime(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_MIME:
            raise ValueError("unsupported visual image MIME type")
        return normalized

    @field_validator("selection_ids", mode="before")
    @classmethod
    def _normalize_selection_ids(cls, value: object) -> list[str]:
        return _bounded_ids(value, max_items=VISUAL_OBSERVATION_MAX_COUNT)

    @field_validator("derived_artifact_ref", mode="before")
    @classmethod
    def _validate_artifact_ref(cls, value: object) -> str | None:
        return _safe_relative_artifact_ref(value)


class VisualObservationProducer(BaseModel):
    """Bounded model/tool identity without credentials or provider URLs."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=200)
    model_version: str | None = Field(default=None, max_length=120)
    tool_name: str | None = Field(default=None, max_length=160)
    tool_version: str | None = Field(default=None, max_length=120)
    server_slug: str | None = Field(default=None, max_length=64)
    server_id: str | None = Field(default=None, max_length=128)
    server_fingerprint: str | None = Field(default=None, max_length=160)
    fingerprint_version: str | None = Field(default=None, max_length=80)

    @field_validator(
        "provider",
        "model",
        "model_version",
        "tool_name",
        "tool_version",
        "server_slug",
        "server_id",
        "fingerprint_version",
        mode="before",
    )
    @classmethod
    def _normalize_optional_text(cls, value: object) -> str | None:
        return _safe_producer_text(value, max_length=200)

    @field_validator("server_fingerprint", mode="before")
    @classmethod
    def _validate_server_fingerprint(cls, value: object) -> str | None:
        normalized = _trimmed(value, max_length=160)
        if normalized is None:
            return None
        normalized = normalized.lower()
        if not _SHA256_RE.fullmatch(normalized):
            return None
        return normalized


class VisualObservationCandidate(BaseModel):
    """One model-derived visual observation linked to a SmartRead turn."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scholar-ai-visual-observation/v1"] = VISUAL_OBSERVATION_SCHEMA_VERSION
    candidate_id: str = Field(min_length=1, max_length=256)
    run_id: str = Field(min_length=1, max_length=256)
    session_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=256)
    order: int = Field(ge=0, lt=VISUAL_OBSERVATION_MAX_COUNT)
    route: VisualObservationRoute
    output_scope: VisualObservationOutputScope
    project_id: str | None = Field(default=None, max_length=128)
    selection_ids: list[str] = Field(default_factory=list, max_length=VISUAL_OBSERVATION_MAX_COUNT)
    image_inputs: list[VisualObservationImageInput] = Field(default_factory=list, max_length=6)
    producer: VisualObservationProducer = Field(default_factory=VisualObservationProducer)
    request_sha256: str = Field(min_length=71, max_length=71)
    cache_status: VisualObservationCacheStatus
    cache_key_hash: str | None = Field(default=None, min_length=71, max_length=71)
    generation_status: VisualObservationGenerationStatus
    review_status: VisualObservationReviewStatus = "candidate"
    freshness_status: VisualObservationFreshnessStatus = "fresh"
    output_text: str | None = Field(default=None, max_length=64_000)
    output_sha256: str | None = Field(default=None, min_length=71, max_length=71)
    error: VisualObservationError | None = None
    source_fingerprints: list[str] = Field(default_factory=list, max_length=12)
    created_at: str = Field(min_length=1, max_length=64)
    updated_at: str = Field(min_length=1, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy_stale_review(cls, value: object) -> object:
        """Map the legacy overloaded stale review state to explicit freshness."""

        if not isinstance(value, Mapping):
            return value
        upgraded = dict(value)
        if upgraded.get("review_status") == "stale":
            upgraded["review_status"] = "candidate"
            upgraded.setdefault("freshness_status", "stale")
        return upgraded

    @field_validator("candidate_id", "run_id", "session_id", "turn_id")
    @classmethod
    def _validate_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("visual observation identifiers have an unsupported shape")
        return normalized

    @field_validator("project_id", mode="before")
    @classmethod
    def _normalize_project_id(cls, value: object) -> str | None:
        normalized = _trimmed(value, max_length=128)
        if normalized is None or not _ID_RE.fullmatch(normalized):
            return None
        return normalized

    @field_validator("output_text", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("selection_ids", mode="before")
    @classmethod
    def _normalize_selection_ids(cls, value: object) -> list[str]:
        return _bounded_ids(value, max_items=VISUAL_OBSERVATION_MAX_COUNT)

    @field_validator("request_sha256", "cache_key_hash", "output_sha256")
    @classmethod
    def _validate_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("visual observation hashes must be sha256:<64 lowercase hex>")
        return normalized

    @field_validator("source_fingerprints", mode="before")
    @classmethod
    def _normalize_source_fingerprints(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        fingerprints: list[str] = []
        for item in value[:12]:
            normalized = _trimmed(item, max_length=71)
            if normalized is not None:
                normalized = normalized.lower()
            if (
                normalized
                and _SHA256_RE.fullmatch(normalized)
                and normalized not in fingerprints
            ):
                fingerprints.append(normalized)
        return fingerprints

    @model_validator(mode="after")
    def _validate_outcome(self) -> "VisualObservationCandidate":
        if not self.image_inputs:
            raise ValueError("visual observations require at least one image input")
        if self.generation_status == "succeeded":
            if not self.output_text or not self.output_sha256:
                raise ValueError("successful visual observations require output text and hash")
            if self.error is not None:
                raise ValueError("successful visual observations must not carry an error")
        else:
            if self.error is None:
                raise ValueError("failed visual observations require an error")
            if self.output_text is not None or self.output_sha256 is not None:
                raise ValueError("failed visual observations must not carry output")
            if self.review_status == "accepted":
                raise ValueError("failed visual observations cannot be accepted")
            if self.cache_status != "unavailable" or self.cache_key_hash is not None:
                raise ValueError("failed visual observations require unavailable cache status")
        if self.cache_status == "hit" and self.cache_key_hash is None:
            raise ValueError("cache hits require cache_key_hash")
        if self.route == "direct_model" and self.output_scope != "answer_joint":
            raise ValueError("direct visual answers must use answer_joint output scope")
        if self.route == "vision_aux_mcp" and self.output_scope != "image_note":
            raise ValueError("vision auxiliary observations must use image_note output scope")
        return self


class VisualObservationSourceRevisionIdentity(BaseModel):
    """One caller-observed source hash replacement used for stale handling."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    previous_source_fingerprint: str = Field(min_length=71, max_length=71)
    current_source_fingerprint: str = Field(min_length=71, max_length=71)

    @field_validator("previous_source_fingerprint", "current_source_fingerprint")
    @classmethod
    def _validate_source_hash(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("source revision fingerprints must use sha256:<64 lowercase hex>")
        return normalized

    @model_validator(mode="after")
    def _require_changed_source(self) -> "VisualObservationSourceRevisionIdentity":
        if self.previous_source_fingerprint == self.current_source_fingerprint:
            raise ValueError("source revision fingerprints must differ")
        return self


class VisualObservationLifecycleRequest(BaseModel):
    """Strict idempotent transition request with dual-axis current-state CAS."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["scholar-ai-visual-observation-lifecycle-request/v1"] = (
        "scholar-ai-visual-observation-lifecycle-request/v1"
    )
    operation_id: str = Field(min_length=1, max_length=256)
    expected_review_status: VisualObservationReviewStatus
    expected_freshness_status: VisualObservationFreshnessStatus
    target_review_status: VisualObservationReviewDecisionStatus | None = None
    target_freshness_status: VisualObservationFreshnessStatus | None = None
    reason: str = Field(min_length=1, max_length=2_000)
    changed_by: str = Field(min_length=1, max_length=256)

    @field_validator("operation_id", "changed_by")
    @classmethod
    def _validate_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("visual lifecycle identifiers have an unsupported shape")
        return normalized

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _validated_audit_text(value, "reason")

    @model_validator(mode="after")
    def _validate_target_axis(self) -> "VisualObservationLifecycleRequest":
        requested = int(self.target_review_status is not None) + int(
            self.target_freshness_status is not None
        )
        if requested != 1:
            raise ValueError("exactly one visual lifecycle target is required")
        if (
            self.target_review_status is not None
            and self.target_review_status == self.expected_review_status
        ):
            raise ValueError("review target must differ from expected review status")
        if (
            self.target_freshness_status is not None
            and self.target_freshness_status == self.expected_freshness_status
        ):
            raise ValueError("freshness target must differ from expected freshness status")
        return self


class VisualObservationSourceRevisionImpact(BaseModel):
    """One candidate and exact current state selected by a read-only preflight."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1, max_length=256)
    expected_review_status: VisualObservationReviewStatus
    expected_freshness_status: VisualObservationFreshnessStatus
    expected_updated_at: datetime

    @field_validator("candidate_id")
    @classmethod
    def _validate_candidate_id(cls, value: str) -> str:
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("visual source revision candidate_id has an unsupported shape")
        return normalized

    @field_validator("expected_updated_at")
    @classmethod
    def _validate_updated_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "expected_updated_at")


class VisualObservationSourceRevisionPreflight(BaseModel):
    """Complete project-scoped impact set whose digest is reused as apply CAS."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scholar-ai-visual-source-revision-preflight/v1"] = (
        "scholar-ai-visual-source-revision-preflight/v1"
    )
    project_id: str = Field(min_length=1, max_length=256)
    operation: VisualObservationSourceRevisionOperation
    source_revision: VisualObservationSourceRevisionIdentity
    impacts: tuple[VisualObservationSourceRevisionImpact, ...] = Field(max_length=500)
    impact_fingerprint: str = Field(min_length=71, max_length=71)

    @field_validator("project_id")
    @classmethod
    def _validate_project_id(cls, value: str) -> str:
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("visual source revision project_id has an unsupported shape")
        return normalized

    @field_validator("impact_fingerprint")
    @classmethod
    def _validate_impact_hash(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("impact_fingerprint must use sha256:<64 lowercase hex>")
        return normalized

    @model_validator(mode="after")
    def _validate_complete_impact_set(self) -> "VisualObservationSourceRevisionPreflight":
        candidate_ids = tuple(impact.candidate_id for impact in self.impacts)
        if candidate_ids != tuple(sorted(candidate_ids)) or len(candidate_ids) != len(
            set(candidate_ids)
        ):
            raise ValueError("source revision impacts must be uniquely sorted by candidate_id")
        expected_status = "fresh" if self.operation == "mark_stale" else "stale"
        if any(
            impact.expected_freshness_status != expected_status for impact in self.impacts
        ):
            raise ValueError("source revision impacts do not match the requested operation")
        expected_hash = visual_observation_source_revision_impact_fingerprint(
            project_id=self.project_id,
            operation=self.operation,
            source_revision=self.source_revision,
            impacts=self.impacts,
        )
        if self.impact_fingerprint != expected_hash:
            raise ValueError("impact_fingerprint does not match the complete impact set")
        return self


class VisualObservationSourceRevisionApplyRequest(BaseModel):
    """Idempotent source-revision apply request bound to one exact preflight."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["scholar-ai-visual-source-revision-apply-request/v1"] = (
        "scholar-ai-visual-source-revision-apply-request/v1"
    )
    operation_id: str = Field(min_length=1, max_length=256)
    project_id: str = Field(min_length=1, max_length=256)
    operation: VisualObservationSourceRevisionOperation
    source_revision: VisualObservationSourceRevisionIdentity
    expected_impact_fingerprint: str = Field(min_length=71, max_length=71)
    validated_candidate_ids: tuple[str, ...] = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=2_000)
    changed_by: str = Field(min_length=1, max_length=256)

    @field_validator("operation_id", "project_id", "changed_by")
    @classmethod
    def _validate_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("visual source revision identifiers have an unsupported shape")
        return normalized

    @field_validator("expected_impact_fingerprint")
    @classmethod
    def _validate_impact_hash(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("expected impact fingerprint must use sha256:<64 lowercase hex>")
        return normalized

    @field_validator("validated_candidate_ids")
    @classmethod
    def _validate_candidate_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not _ID_RE.fullmatch(item) for item in normalized):
            raise ValueError("validated candidate ids contain an unsupported identifier")
        if normalized != tuple(sorted(normalized)) or len(normalized) != len(set(normalized)):
            raise ValueError("validated candidate ids must be unique and sorted")
        return normalized

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _validated_audit_text(value, "reason")


class VisualObservationLifecycleEvent(BaseModel):
    """Durable audit event for one committed visual lifecycle transition."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["scholar-ai-visual-lifecycle-event/v1"] = (
        "scholar-ai-visual-lifecycle-event/v1"
    )
    event_id: str = Field(min_length=1, max_length=256)
    operation_id: str = Field(min_length=1, max_length=256)
    candidate_id: str = Field(min_length=1, max_length=256)
    session_id: str = Field(min_length=1, max_length=256)
    project_id: str | None = Field(default=None, min_length=1, max_length=256)
    axis: VisualObservationLifecycleAxis
    from_status: VisualObservationLifecycleStatus
    to_status: VisualObservationLifecycleStatus
    previous_review_status: VisualObservationReviewStatus
    previous_freshness_status: VisualObservationFreshnessStatus
    result_review_status: VisualObservationReviewStatus
    result_freshness_status: VisualObservationFreshnessStatus
    reason: str = Field(min_length=1, max_length=2_000)
    changed_by: str = Field(min_length=1, max_length=256)
    occurred_at: datetime
    source_revision_receipt_id: str | None = Field(default=None, min_length=1, max_length=256)
    source_revision_operation: VisualObservationSourceRevisionOperation | None = None
    source_revision: VisualObservationSourceRevisionIdentity | None = None
    source_revision_impact_fingerprint: str | None = Field(
        default=None,
        min_length=71,
        max_length=71,
    )

    @field_validator(
        "event_id",
        "operation_id",
        "candidate_id",
        "session_id",
        "project_id",
        "changed_by",
        "source_revision_receipt_id",
    )
    @classmethod
    def _validate_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("visual lifecycle event identifiers have an unsupported shape")
        return normalized

    @field_validator("source_revision_impact_fingerprint")
    @classmethod
    def _validate_optional_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("source revision event hash must use sha256:<64 lowercase hex>")
        return normalized

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _validated_audit_text(value, "reason")

    @field_validator("occurred_at")
    @classmethod
    def _validate_occurred_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "occurred_at")

    @model_validator(mode="after")
    def _validate_transition_shape(self) -> "VisualObservationLifecycleEvent":
        if self.from_status == self.to_status:
            raise ValueError("lifecycle events must record a changed status")
        if self.axis == "review":
            if self.from_status not in _REVIEW_STATUSES or self.to_status not in _REVIEW_TARGETS:
                raise ValueError("review event statuses are invalid")
            if (
                self.from_status != self.previous_review_status
                or self.to_status != self.result_review_status
                or self.previous_freshness_status != self.result_freshness_status
            ):
                raise ValueError("review event axes are inconsistent")
        elif (
            self.from_status not in _FRESHNESS_STATUSES
            or self.to_status not in _FRESHNESS_STATUSES
            or self.from_status != self.previous_freshness_status
            or self.to_status != self.result_freshness_status
            or self.previous_review_status != self.result_review_status
        ):
            raise ValueError("freshness event axes are inconsistent")

        source_fields = (
            self.source_revision_receipt_id,
            self.source_revision_operation,
            self.source_revision,
            self.source_revision_impact_fingerprint,
        )
        if any(item is not None for item in source_fields):
            if any(item is None for item in source_fields) or self.axis != "freshness":
                raise ValueError("source revision event metadata must be complete and freshness-only")
            expected_pair = (
                ("fresh", "stale")
                if self.source_revision_operation == "mark_stale"
                else ("stale", "fresh")
            )
            if (self.from_status, self.to_status) != expected_pair:
                raise ValueError("source revision event direction does not match its operation")
        return self


class VisualObservationLifecycleReceipt(BaseModel):
    """Durable idempotency receipt for one explicit candidate transition."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["scholar-ai-visual-lifecycle-receipt/v1"] = (
        "scholar-ai-visual-lifecycle-receipt/v1"
    )
    receipt_id: str = Field(min_length=1, max_length=256)
    operation_id: str = Field(min_length=1, max_length=256)
    request_sha256: str = Field(min_length=71, max_length=71)
    event_id: str = Field(min_length=1, max_length=256)
    candidate_id: str = Field(min_length=1, max_length=256)
    session_id: str = Field(min_length=1, max_length=256)
    project_id: str | None = Field(default=None, min_length=1, max_length=256)
    axis: VisualObservationLifecycleAxis
    from_status: VisualObservationLifecycleStatus
    to_status: VisualObservationLifecycleStatus
    previous_review_status: VisualObservationReviewStatus
    previous_freshness_status: VisualObservationFreshnessStatus
    result_review_status: VisualObservationReviewStatus
    result_freshness_status: VisualObservationFreshnessStatus
    reason: str = Field(min_length=1, max_length=2_000)
    changed_by: str = Field(min_length=1, max_length=256)
    occurred_at: datetime

    @field_validator(
        "receipt_id",
        "operation_id",
        "event_id",
        "candidate_id",
        "session_id",
        "project_id",
        "changed_by",
    )
    @classmethod
    def _validate_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("visual lifecycle receipt identifiers have an unsupported shape")
        return normalized

    @field_validator("request_sha256")
    @classmethod
    def _validate_request_hash(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("request_sha256 must use sha256:<64 lowercase hex>")
        return normalized

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _validated_audit_text(value, "reason")

    @field_validator("occurred_at")
    @classmethod
    def _validate_occurred_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "occurred_at")

    @model_validator(mode="after")
    def _validate_receipt_transition(self) -> "VisualObservationLifecycleReceipt":
        request = VisualObservationLifecycleRequest(
            operation_id=self.operation_id,
            expected_review_status=self.previous_review_status,
            expected_freshness_status=self.previous_freshness_status,
            target_review_status=(
                self.result_review_status if self.axis == "review" else None
            ),
            target_freshness_status=(
                self.result_freshness_status if self.axis == "freshness" else None
            ),
            reason=self.reason,
            changed_by=self.changed_by,
        )
        if self.request_sha256 != visual_observation_lifecycle_request_hash(request):
            raise ValueError("request_sha256 does not match lifecycle receipt content")
        expected_from = (
            self.previous_review_status
            if self.axis == "review"
            else self.previous_freshness_status
        )
        expected_to = (
            self.result_review_status
            if self.axis == "review"
            else self.result_freshness_status
        )
        if self.from_status != expected_from or self.to_status != expected_to:
            raise ValueError("receipt status pair does not match its lifecycle axis")
        if self.axis == "review" and self.previous_freshness_status != self.result_freshness_status:
            raise ValueError("review receipt cannot change freshness")
        if self.axis == "freshness" and self.previous_review_status != self.result_review_status:
            raise ValueError("freshness receipt cannot change review state")
        return self


class VisualObservationSourceRevisionApplyReceipt(BaseModel):
    """Durable aggregate receipt for one atomic source revision application."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    schema_version: Literal["scholar-ai-visual-source-revision-receipt/v1"] = (
        "scholar-ai-visual-source-revision-receipt/v1"
    )
    receipt_id: str = Field(min_length=1, max_length=256)
    operation_id: str = Field(min_length=1, max_length=256)
    request_sha256: str = Field(min_length=71, max_length=71)
    project_id: str = Field(min_length=1, max_length=256)
    operation: VisualObservationSourceRevisionOperation
    source_revision: VisualObservationSourceRevisionIdentity
    impact_fingerprint: str = Field(min_length=71, max_length=71)
    candidate_ids: tuple[str, ...] = Field(min_length=1, max_length=500)
    events: tuple[VisualObservationLifecycleEvent, ...] = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=2_000)
    changed_by: str = Field(min_length=1, max_length=256)
    occurred_at: datetime

    @field_validator("receipt_id", "operation_id", "project_id", "changed_by")
    @classmethod
    def _validate_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("visual source revision receipt identifiers have an unsupported shape")
        return normalized

    @field_validator("request_sha256", "impact_fingerprint")
    @classmethod
    def _validate_hash(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("source revision receipt hashes must use sha256:<64 lowercase hex>")
        return normalized

    @field_validator("candidate_ids")
    @classmethod
    def _validate_candidate_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not _ID_RE.fullmatch(item) for item in value):
            raise ValueError("source revision receipt has an invalid candidate id")
        if value != tuple(sorted(value)) or len(value) != len(set(value)):
            raise ValueError("source revision receipt candidate ids must be unique and sorted")
        return value

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _validated_audit_text(value, "reason")

    @field_validator("occurred_at")
    @classmethod
    def _validate_occurred_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "occurred_at")

    @model_validator(mode="after")
    def _validate_receipt_events(self) -> "VisualObservationSourceRevisionApplyReceipt":
        event_candidate_ids = tuple(event.candidate_id for event in self.events)
        if event_candidate_ids != self.candidate_ids:
            raise ValueError("source revision receipt events do not match candidate_ids")
        for event in self.events:
            if (
                event.operation_id != self.operation_id
                or event.project_id != self.project_id
                or event.source_revision_receipt_id != self.receipt_id
                or event.source_revision_operation != self.operation
                or event.source_revision != self.source_revision
                or event.source_revision_impact_fingerprint != self.impact_fingerprint
                or event.reason != self.reason
                or event.changed_by != self.changed_by
                or event.occurred_at != self.occurred_at
            ):
                raise ValueError("source revision receipt contains an inconsistent event")
        request = VisualObservationSourceRevisionApplyRequest(
            operation_id=self.operation_id,
            project_id=self.project_id,
            operation=self.operation,
            source_revision=self.source_revision,
            expected_impact_fingerprint=self.impact_fingerprint,
            validated_candidate_ids=self.candidate_ids,
            reason=self.reason,
            changed_by=self.changed_by,
        )
        if self.request_sha256 != visual_observation_source_revision_request_hash(request):
            raise ValueError("request_sha256 does not match source revision receipt content")
        return self


def visual_observation_lifecycle_request_hash(
    request: VisualObservationLifecycleRequest,
) -> str:
    """Hash the complete validated transition request for idempotency checks."""

    if not isinstance(request, VisualObservationLifecycleRequest):
        raise TypeError("request must be VisualObservationLifecycleRequest")
    return _canonical_sha256(request.model_dump(mode="json"))


def visual_observation_source_revision_impact_fingerprint(
    *,
    project_id: str,
    operation: VisualObservationSourceRevisionOperation,
    source_revision: VisualObservationSourceRevisionIdentity,
    impacts: tuple[VisualObservationSourceRevisionImpact, ...],
) -> str:
    """Hash the complete caller-visible impact set reused by apply CAS."""

    return _canonical_sha256(
        {
            "project_id": project_id,
            "operation": operation,
            "source_revision": source_revision.model_dump(mode="json"),
            "impacts": [impact.model_dump(mode="json") for impact in impacts],
        }
    )


def visual_observation_source_revision_request_hash(
    request: VisualObservationSourceRevisionApplyRequest,
) -> str:
    """Hash one validated source revision apply request for durable replay."""

    if not isinstance(request, VisualObservationSourceRevisionApplyRequest):
        raise TypeError("request must be VisualObservationSourceRevisionApplyRequest")
    return _canonical_sha256(request.model_dump(mode="json"))


@dataclass(frozen=True, slots=True)
class VisualObservationMutationResult:
    """Candidate snapshot, event, durable receipt, and replay indicator."""

    candidate: VisualObservationCandidate
    event: VisualObservationLifecycleEvent
    receipt: VisualObservationLifecycleReceipt
    replayed: bool


@dataclass(frozen=True, slots=True)
class VisualObservationSourceRevisionResult:
    """Aggregate source revision receipt and replay indicator."""

    receipt: VisualObservationSourceRevisionApplyReceipt
    replayed: bool


class VisualObservationReference(BaseModel):
    """Compact reference safe for normal responses, history, and receipts."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scholar-ai-visual-observation-ref/v1"] = (
        VISUAL_OBSERVATION_REF_SCHEMA_VERSION
    )
    candidate_id: str = Field(min_length=1, max_length=256)
    turn_id: str = Field(min_length=1, max_length=256)
    route: VisualObservationRoute
    generation_status: VisualObservationGenerationStatus
    review_status: VisualObservationReferenceReviewStatus
    selection_ids: list[str] = Field(default_factory=list, max_length=VISUAL_OBSERVATION_MAX_COUNT)
    output_sha256: str | None = Field(default=None, min_length=71, max_length=71)
    cache_status: VisualObservationCacheStatus
    cache_key_hash: str | None = Field(default=None, min_length=71, max_length=71)
    read_endpoint: str = Field(min_length=1, max_length=500)

    @field_validator("candidate_id", "turn_id")
    @classmethod
    def _validate_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not _ID_RE.fullmatch(normalized):
            raise ValueError("visual observation reference identifiers have an unsupported shape")
        return normalized

    @field_validator("selection_ids", mode="before")
    @classmethod
    def _normalize_selection_ids(cls, value: object) -> list[str]:
        return _bounded_ids(value, max_items=VISUAL_OBSERVATION_MAX_COUNT)

    @field_validator("output_sha256", "cache_key_hash")
    @classmethod
    def _validate_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("visual observation reference hashes must use sha256")
        return normalized

    @model_validator(mode="after")
    def _validate_cache_hit(self) -> "VisualObservationReference":
        if self.cache_status == "hit" and self.cache_key_hash is None:
            raise ValueError("cache hits require cache_key_hash")
        if self.generation_status == "succeeded" and self.output_sha256 is None:
            raise ValueError("successful visual observation references require output_sha256")
        if self.generation_status == "failed":
            if self.output_sha256 is not None:
                raise ValueError("failed visual observation references must not carry output_sha256")
            if self.cache_status != "unavailable" or self.cache_key_hash is not None:
                raise ValueError(
                    "failed visual observation references require unavailable cache status"
                )
        expected_endpoint = f"/api/chat/visual-observations/{self.candidate_id}"
        if self.read_endpoint != expected_endpoint:
            raise ValueError("visual observation read endpoint must match candidate_id")
        return self


def _bounded_ids(value: object, *, max_items: int) -> list[str]:
    if not isinstance(value, list):
        return []
    identifiers: list[str] = []
    for item in value[:max_items]:
        normalized = _trimmed(item, max_length=256)
        if normalized and _ID_RE.fullmatch(normalized) and normalized not in identifiers:
            identifiers.append(normalized)
    return identifiers


_IMAGE_INPUT_KEYS = frozenset(
    {
        "image_id",
        "content_sha256",
        "mime",
        "size",
        "selection_ids",
        "derived_artifact_ref",
        "artifact_sha256",
    }
)
_PRODUCER_KEYS = frozenset(
    {
        "provider",
        "model",
        "model_version",
        "tool_name",
        "tool_version",
        "server_slug",
        "server_id",
        "server_fingerprint",
        "fingerprint_version",
    }
)
_ERROR_KEYS = frozenset({"code", "message", "recoverable"})
_CANDIDATE_KEYS = frozenset(
    {
        "schema_version",
        "candidate_id",
        "run_id",
        "session_id",
        "turn_id",
        "order",
        "route",
        "output_scope",
        "project_id",
        "selection_ids",
        "image_inputs",
        "producer",
        "request_sha256",
        "cache_status",
        "cache_key_hash",
        "generation_status",
        "review_status",
        "freshness_status",
        "output_text",
        "output_sha256",
        "error",
        "source_fingerprints",
        "created_at",
        "updated_at",
    }
)
_REFERENCE_KEYS = frozenset(
    {
        "schema_version",
        "candidate_id",
        "turn_id",
        "route",
        "generation_status",
        "review_status",
        "selection_ids",
        "output_sha256",
        "cache_status",
        "cache_key_hash",
        "read_endpoint",
    }
)


def sanitize_visual_observations(value: object) -> list[dict[str, Any]]:
    """Return bounded visual candidate records with all pixel/path fields removed.

    Args:
        value: Untrusted JSON-like history value.

    Returns:
        Valid candidate dictionaries. Invalid entries are dropped independently.
    """

    if not isinstance(value, list):
        return []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value[:VISUAL_OBSERVATION_MAX_COUNT]:
        raw = _allowlisted_mapping(item, _CANDIDATE_KEYS)
        if not raw or raw.get("schema_version") not in {None, VISUAL_OBSERVATION_SCHEMA_VERSION}:
            continue
        raw["schema_version"] = VISUAL_OBSERVATION_SCHEMA_VERSION
        raw_images = raw.get("image_inputs")
        raw["image_inputs"] = (
            [_allowlisted_mapping(image, _IMAGE_INPUT_KEYS) for image in raw_images[:6]]
            if isinstance(raw_images, list)
            else []
        )
        raw["producer"] = _allowlisted_mapping(raw.get("producer"), _PRODUCER_KEYS)
        if raw.get("error") is not None:
            raw["error"] = _allowlisted_mapping(raw.get("error"), _ERROR_KEYS)
        try:
            candidate = VisualObservationCandidate.model_validate(raw)
        except (TypeError, ValueError):
            continue
        if candidate.candidate_id in seen:
            continue
        seen.add(candidate.candidate_id)
        records.append(candidate.model_dump(mode="json", exclude_none=True))
    return records


def visual_observation_reference(
    candidate: VisualObservationCandidate | Mapping[str, Any],
) -> VisualObservationReference:
    """Build a compact reference from a validated visual candidate."""

    record = (
        candidate
        if isinstance(candidate, VisualObservationCandidate)
        else VisualObservationCandidate.model_validate(dict(candidate))
    )
    return VisualObservationReference(
        candidate_id=record.candidate_id,
        turn_id=record.turn_id,
        route=record.route,
        generation_status=record.generation_status,
        review_status=record.review_status,
        selection_ids=list(record.selection_ids),
        output_sha256=record.output_sha256,
        cache_status=record.cache_status,
        cache_key_hash=record.cache_key_hash,
        read_endpoint=f"/api/chat/visual-observations/{record.candidate_id}",
    )


def sanitize_visual_observation_refs(value: object) -> list[dict[str, Any]]:
    """Return bounded, output-free visual observation references."""

    if not isinstance(value, list):
        return []
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value[:VISUAL_OBSERVATION_MAX_COUNT]:
        raw = _allowlisted_mapping(item, _REFERENCE_KEYS)
        if not raw or raw.get("schema_version") not in {
            None,
            VISUAL_OBSERVATION_REF_SCHEMA_VERSION,
        }:
            continue
        raw["schema_version"] = VISUAL_OBSERVATION_REF_SCHEMA_VERSION
        try:
            ref = VisualObservationReference.model_validate(raw)
        except (TypeError, ValueError):
            continue
        if ref.candidate_id in seen:
            continue
        seen.add(ref.candidate_id)
        refs.append(ref.model_dump(mode="json", exclude_none=True))
    return refs


@dataclass(frozen=True, slots=True)
class VisualObservationTransition:
    """Result of evaluating one review-state transition."""

    allowed: bool
    no_op: bool
    reason: str


def evaluate_visual_observation_transition(
    *,
    generation_status: VisualObservationGenerationStatus,
    current: VisualObservationReviewStatus,
    target: VisualObservationReviewStatus,
) -> VisualObservationTransition:
    """Evaluate the strict review state machine without side effects."""

    if current == target:
        return VisualObservationTransition(True, True, f"already {current}")
    if target == "accepted" and generation_status != "succeeded":
        return VisualObservationTransition(False, False, "failed observations cannot be accepted")
    allowed: dict[VisualObservationReviewStatus, frozenset[VisualObservationReviewStatus]] = {
        "candidate": frozenset({"accepted", "rejected", "withdrawn"}),
        "accepted": frozenset({"rejected", "withdrawn"}),
        "rejected": frozenset({"withdrawn"}),
        "withdrawn": frozenset(),
    }
    if target in allowed[current]:
        return VisualObservationTransition(True, False, f"{current} -> {target}")
    return VisualObservationTransition(False, False, f"forbidden: {current} -> {target}")


def evaluate_visual_observation_freshness_transition(
    *,
    current: VisualObservationFreshnessStatus,
    target: VisualObservationFreshnessStatus,
) -> VisualObservationTransition:
    """Evaluate an explicit freshness transition without changing review state."""

    if current == target:
        return VisualObservationTransition(True, True, f"already {current}")
    if {current, target} == {"fresh", "stale"}:
        return VisualObservationTransition(True, False, f"{current} -> {target}")
    return VisualObservationTransition(False, False, f"forbidden: {current} -> {target}")


__all__ = [
    "VISUAL_OBSERVATION_REF_SCHEMA_VERSION",
    "VISUAL_OBSERVATION_SCHEMA_VERSION",
    "VisualObservationCandidate",
    "VisualObservationFreshnessStatus",
    "VisualObservationLifecycleAxis",
    "VisualObservationLifecycleEvent",
    "VisualObservationLifecycleReceipt",
    "VisualObservationLifecycleRequest",
    "VisualObservationLifecycleStatus",
    "VisualObservationMutationResult",
    "VisualObservationReference",
    "VisualObservationReviewDecisionStatus",
    "VisualObservationReviewStatus",
    "VisualObservationSourceRevisionApplyReceipt",
    "VisualObservationSourceRevisionApplyRequest",
    "VisualObservationSourceRevisionIdentity",
    "VisualObservationSourceRevisionImpact",
    "VisualObservationSourceRevisionOperation",
    "VisualObservationSourceRevisionPreflight",
    "VisualObservationSourceRevisionResult",
    "evaluate_visual_observation_freshness_transition",
    "evaluate_visual_observation_transition",
    "sanitize_visual_observation_refs",
    "sanitize_visual_observations",
    "visual_observation_lifecycle_request_hash",
    "visual_observation_reference",
    "visual_observation_source_revision_impact_fingerprint",
    "visual_observation_source_revision_request_hash",
    "visual_material_source_binding_fingerprint",
]
