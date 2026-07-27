"""Strict contracts for compliant literature acquisition.

The acquisition layer persists only bounded metadata, sanitized public URLs,
and project-relative artifact labels. Browser state, credentials, signed URLs,
and absolute local paths are deliberately outside these contracts.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


ACQUISITION_SCHEMA_VERSION = "scholar-ai-acquisition/v1"
MAX_SEARCH_SOURCES = 8
MAX_CANDIDATES_PER_RUN = 200
MAX_SOURCE_ERRORS = 32
MAX_AUTHORS = 100
MAX_SOURCE_RECORDS_PER_CANDIDATE = 32
MAX_IDENTITY_EVIDENCE_ITEMS = 8

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SOURCE_RECORD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,299}$")
_SOURCE_REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,79}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
_ARXIV_VERSION_RE = re.compile(r"v\d+$", re.IGNORECASE)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CREDENTIAL_RE = re.compile(
    r"(?:\b(?:authorization|api[-_ ]?key|access[-_ ]?token|refresh[-_ ]?token|"
    r"password|client[-_ ]?secret)\s*[:=]\s*\S+|"
    r"\bbearer\s+[A-Za-z0-9._=+/-]{8,})",
    re.IGNORECASE,
)


def utc_now() -> datetime:
    """Return one timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def normalize_doi(value: str | None) -> str | None:
    """Normalize a DOI without treating a resolver URL as separate identity."""

    if value is None:
        return None
    normalized = _DOI_PREFIX_RE.sub("", str(value).strip()).lower().rstrip(" .")
    if not normalized:
        return None
    if not normalized.startswith("10.") or "/" not in normalized or len(normalized) > 300:
        raise ValueError("doi has an unsupported shape")
    return normalized


def normalize_arxiv_id(value: str | None) -> str | None:
    """Normalize an arXiv identifier while retaining the paper identity."""

    if value is None:
        return None
    normalized = str(value).strip()
    normalized = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"^arxiv:\s*", "", normalized, flags=re.IGNORECASE)
    normalized = normalized.removesuffix(".pdf")
    normalized = _ARXIV_VERSION_RE.sub("", normalized).lower()
    if not re.fullmatch(r"(?:[a-z.-]+/\d{7}|\d{4}\.\d{4,5})", normalized):
        raise ValueError("arxiv_id has an unsupported shape")
    return normalized


def normalize_title(value: str) -> str:
    """Return a conservative normalized-title identity key."""

    collapsed = re.sub(r"\s+", " ", value.strip().casefold())
    return re.sub(r"[^\w]+", "", collapsed, flags=re.UNICODE)


def _author_identity_keys(authors: tuple[str, ...]) -> frozenset[str]:
    """Return conservative full-name keys independent of token ordering."""

    keys: set[str] = set()
    for author in authors:
        tokens = re.findall(r"\w+", author.casefold(), flags=re.UNICODE)
        if tokens:
            keys.add("\0".join(sorted(tokens)))
    return frozenset(keys)


def sanitize_public_https_url(value: str, *, field_name: str = "url") -> str:
    """Validate a persistable public HTTPS URL without secrets or selectors.

    Host allowlisting and public-IP resolution are runtime network checks. This
    model-level guard prevents durable state from containing credentials,
    query strings, fragments, non-HTTPS schemes, or non-default ports.
    """

    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError(f"{field_name} must be an absolute HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field_name} must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{field_name} must not contain query strings or fragments")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field_name} has an invalid port") from exc
    if port not in (None, 443):
        raise ValueError(f"{field_name} must use the default HTTPS port")
    host = parsed.hostname.rstrip(".").lower()
    if not host or _CREDENTIAL_RE.search(normalized):
        raise ValueError(f"{field_name} is not safe to persist")
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit(("https", netloc, parsed.path or "/", "", ""))


def normalize_relative_artifact_path(value: str) -> str:
    """Return a canonical project-relative artifact label."""

    normalized = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts or ":" in path.parts[0]:
        raise ValueError("artifact path must be project-relative")
    if any(part in {"", "."} for part in path.parts):
        raise ValueError("artifact path contains an invalid segment")
    return path.as_posix()


def _validate_id(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not _ID_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} has an unsupported identifier shape")
    return normalized


def _validate_source_id(value: str, field_name: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SOURCE_ID_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} has an unsupported source identifier")
    return normalized


def _validate_safe_text(value: str, field_name: str) -> str:
    normalized = re.sub(r"\s+", " ", _CONTROL_RE.sub("", str(value or ""))).strip()
    if _CREDENTIAL_RE.search(normalized):
        raise ValueError(f"{field_name} must not contain credentials")
    return normalized


def _validate_aware_timestamp(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(timezone.utc)


def _validation_field_name(info: ValidationInfo) -> str:
    """Return the field name guaranteed by a field-validator context.

    Args:
        info: Pydantic validation metadata supplied to a field validator.

    Returns:
        The concrete model field name for validation error reporting.

    Raises:
        ValueError: If the validator is invoked without a model-field context.
    """

    field_name = info.field_name
    if field_name is None:
        raise ValueError("field validator requires a model-field context")
    return field_name


class StrictRecord(BaseModel):
    """Base class for immutable, extra-forbidding persisted records."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SearchRunStatus(str, Enum):
    """Durable search-run lifecycle."""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class DownloadJobStatus(str, Enum):
    """Durable download lifecycle with explicit user-owned gates."""

    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    HUMAN_REQUIRED = "human_required"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ImportStatus(str, Enum):
    """Existing-project import lifecycle."""

    QUEUED = "queued"
    COMPLETED = "completed"
    DUPLICATE = "duplicate"
    FAILED = "failed"


class ImportPublicationState(str, Enum):
    """Publication-integrity state attached to one durable import receipt."""

    UNVERIFIED_LEGACY = "unverified_legacy"
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"


class GateStatus(str, Enum):
    """Human access gate state."""

    OPEN = "open"
    RESOLVED = "resolved"


class AcquisitionAttemptStage(str, Enum):
    """Audited acquisition operation stages."""

    SEARCH = "search"
    DOWNLOAD = "download"


class AcquisitionAttemptOutcome(str, Enum):
    """Terminal outcome of one append-only acquisition attempt."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    HUMAN_REQUIRED = "human_required"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class ArtifactPromotionState(str, Enum):
    """Two-phase durable state around atomic filesystem promotion."""

    PREPARED = "prepared"
    PROMOTED = "promoted"


class AccessRoute(str, Enum):
    """How full text may lawfully be accessed."""

    OPEN_ACCESS = "open_access"
    INSTITUTION_BROWSER = "institution_browser"
    MANUAL_REVIEW = "manual_review"
    UNAVAILABLE = "unavailable"


class AccessEvidenceKind(str, Enum):
    """Evidence classes accepted by source policy."""

    OFFICIAL_REPOSITORY = "official_repository"
    OA_API = "oa_api"
    MANUAL_REVIEW = "manual_review"


class IdentityMatchMethod(str, Enum):
    """Strength-ordered candidate identity methods."""

    DOI = "doi"
    ARXIV_ID = "arxiv_id"
    TITLE_YEAR = "title_year"
    DISTINCT = "distinct"


class IdentityDecisionOutcome(str, Enum):
    """Whether one compared candidate was merged into the canonical record."""

    MATCH = "match"
    DISTINCT = "distinct"


class PublicationStage(str, Enum):
    """Explicit source-reported stage used only for conservative version links."""

    UNKNOWN = "unknown"
    PREPRINT = "preprint"
    PUBLISHED = "published"


class VersionRelationType(str, Enum):
    """Directed relation from one retained candidate version to another."""

    REVISION_OF = "revision_of"
    PREPRINT_OF = "preprint_of"


class VersionRelationEvidenceKind(str, Enum):
    """Allowlisted evidence that can create a durable version edge."""

    SOURCE_REVISION = "source_revision"
    DOI_AND_SOURCE_STAGE = "doi_and_source_stage"


class SourcePolicy(StrictRecord):
    """Allowlisted capabilities and hosts for one source adapter."""

    source_id: str
    capabilities: tuple[Literal["search", "download"], ...]
    metadata_hosts: tuple[str, ...] = ()
    download_hosts: tuple[str, ...] = ()
    evidence_kinds: tuple[AccessEvidenceKind, ...]
    requires_authentication: bool = False
    enabled: bool = True
    min_interval_seconds: float = Field(default=3.0, ge=0.0, le=120.0)
    max_results_per_query: int = Field(default=50, ge=1, le=200)
    terms_url: str

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return _validate_source_id(value, "source_id")

    @field_validator("metadata_hosts", "download_hosts", mode="before")
    @classmethod
    def _hosts(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("hosts must be a sequence")
        hosts: list[str] = []
        for item in value:
            host = str(item or "").strip().rstrip(".").lower()
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host):
                raise ValueError("host has an unsupported shape")
            if "*" in host or host not in hosts:
                if "*" in host:
                    raise ValueError("host allowlists require exact names")
                hosts.append(host)
        return tuple(hosts)

    @field_validator("capabilities", "evidence_kinds", mode="before")
    @classmethod
    def _dedupe_values(cls, value: object) -> tuple[object, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("policy values must be a sequence")
        return tuple(dict.fromkeys(value))

    @field_validator("terms_url")
    @classmethod
    def _terms_url(cls, value: str) -> str:
        return sanitize_public_https_url(value, field_name="terms_url")

    @model_validator(mode="after")
    def _policy_shape(self) -> "SourcePolicy":
        if "search" in self.capabilities and not self.metadata_hosts:
            raise ValueError("search capability requires metadata_hosts")
        if "download" in self.capabilities and not self.download_hosts:
            raise ValueError("download capability requires download_hosts")
        if not self.evidence_kinds:
            raise ValueError("source policy requires evidence_kinds")
        return self


class SearchQuery(StrictRecord):
    """One bounded, project-scoped literature search request."""

    project_id: str
    query: str = Field(min_length=1, max_length=1_000)
    sources: tuple[str, ...] = Field(min_length=1, max_length=MAX_SEARCH_SOURCES)
    max_results: int = Field(default=20, ge=1, le=MAX_CANDIDATES_PER_RUN)
    year_from: int | None = Field(default=None, ge=1800, le=2200)
    year_to: int | None = Field(default=None, ge=1800, le=2200)

    @field_validator("project_id")
    @classmethod
    def _project_id(cls, value: str) -> str:
        return _validate_id(value, "project_id")

    @field_validator("query")
    @classmethod
    def _query(cls, value: str) -> str:
        normalized = _validate_safe_text(value, "query")
        if not normalized:
            raise ValueError("query must be non-empty")
        return normalized

    @field_validator("sources", mode="before")
    @classmethod
    def _sources(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("sources must be a sequence")
        sources = tuple(dict.fromkeys(_validate_source_id(str(item), "sources") for item in value))
        if not sources or len(sources) > MAX_SEARCH_SOURCES:
            raise ValueError(f"sources accepts 1 through {MAX_SEARCH_SOURCES} values")
        return sources

    @model_validator(mode="after")
    def _year_range(self) -> "SearchQuery":
        if self.year_from is not None and self.year_to is not None and self.year_to < self.year_from:
            raise ValueError("year_to must be greater than or equal to year_from")
        return self


class AccessEvidence(StrictRecord):
    """Explicit evidence that one exact PDF route is lawfully downloadable."""

    evidence_id: str
    candidate_id: str
    source_platform: str
    kind: AccessEvidenceKind
    access_route: AccessRoute
    pdf_url: str
    statement: str = Field(min_length=1, max_length=500)
    license: str | None = Field(default=None, max_length=120)
    observed_at: datetime = Field(default_factory=utc_now)

    @field_validator("evidence_id", "candidate_id")
    @classmethod
    def _ids(cls, value: str, info: ValidationInfo) -> str:
        return _validate_id(value, _validation_field_name(info))

    @field_validator("source_platform")
    @classmethod
    def _source(cls, value: str) -> str:
        return _validate_source_id(value, "source_platform")

    @field_validator("pdf_url")
    @classmethod
    def _pdf_url(cls, value: str) -> str:
        return sanitize_public_https_url(value, field_name="pdf_url")

    @field_validator("statement", "license")
    @classmethod
    def _text(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        normalized = _validate_safe_text(value, _validation_field_name(info))
        return normalized or None

    @field_validator("observed_at")
    @classmethod
    def _observed_at(cls, value: datetime) -> datetime:
        return _validate_aware_timestamp(value, "observed_at")

    @model_validator(mode="after")
    def _automatic_route(self) -> "AccessEvidence":
        if self.access_route is not AccessRoute.OPEN_ACCESS:
            raise ValueError("automatic AccessEvidence must use open_access")
        return self


class PdfCandidate(StrictRecord):
    """One exact PDF URL and its matching access evidence."""

    pdf_url: str
    source_platform: str
    access_evidence: AccessEvidence

    @field_validator("pdf_url")
    @classmethod
    def _url(cls, value: str) -> str:
        return sanitize_public_https_url(value, field_name="pdf_url")

    @field_validator("source_platform")
    @classmethod
    def _source(cls, value: str) -> str:
        return _validate_source_id(value, "source_platform")

    @model_validator(mode="after")
    def _same_route(self) -> "PdfCandidate":
        if self.access_evidence.pdf_url != self.pdf_url:
            raise ValueError("access evidence must describe the same PDF URL")
        if self.access_evidence.source_platform != self.source_platform:
            raise ValueError("access evidence must describe the same source")
        return self


class CandidateSourceRecord(StrictRecord):
    """Exact source record identity retained across candidate merges."""

    source_platform: str
    source_record_id: str
    source_revision: str | None = None
    publication_stage: PublicationStage = PublicationStage.UNKNOWN

    @field_validator("source_platform")
    @classmethod
    def _source(cls, value: str) -> str:
        return _validate_source_id(value, "source_platform")

    @field_validator("source_record_id")
    @classmethod
    def _record_id(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not _SOURCE_RECORD_ID_RE.fullmatch(normalized):
            raise ValueError("source_record_id has an unsupported identifier shape")
        return normalized

    @field_validator("source_revision")
    @classmethod
    def _revision(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not _SOURCE_REVISION_RE.fullmatch(normalized):
            raise ValueError("source_revision has an unsupported identifier shape")
        return normalized


class CandidateManifest(StrictRecord):
    """Normalized candidate with merged source and access provenance."""

    candidate_id: str
    run_id: str
    project_id: str
    title: str = Field(min_length=1, max_length=2_000)
    authors: tuple[str, ...] = Field(default=(), max_length=MAX_AUTHORS)
    year: int | None = Field(default=None, ge=1800, le=2200)
    published_date: str | None = Field(default=None, max_length=40)
    abstract: str | None = Field(default=None, max_length=20_000)
    doi: str | None = Field(default=None, max_length=300)
    arxiv_id: str | None = Field(default=None, max_length=80)
    source_platforms: tuple[str, ...] = Field(min_length=1, max_length=MAX_SEARCH_SOURCES)
    source_records: tuple[CandidateSourceRecord, ...] = Field(
        default=(),
        max_length=MAX_SOURCE_RECORDS_PER_CANDIDATE,
    )
    landing_urls: tuple[str, ...] = Field(default=(), max_length=16)
    pdf_candidates: tuple[PdfCandidate, ...] = Field(default=(), max_length=16)
    merged_from_candidate_ids: tuple[str, ...] = Field(default=(), max_length=64)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("candidate_id", "run_id", "project_id")
    @classmethod
    def _ids(cls, value: str, info: ValidationInfo) -> str:
        return _validate_id(value, _validation_field_name(info))

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        normalized = _validate_safe_text(value, "title")
        if not normalized:
            raise ValueError("title must be non-empty")
        return normalized

    @field_validator("authors", mode="before")
    @classmethod
    def _authors(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("authors must be a sequence")
        authors: list[str] = []
        for item in value:
            author = _validate_safe_text(str(item), "authors")
            if author and author not in authors:
                authors.append(author[:500])
        if len(authors) > MAX_AUTHORS:
            raise ValueError(f"authors accepts at most {MAX_AUTHORS} values")
        return tuple(authors)

    @field_validator("doi", mode="before")
    @classmethod
    def _doi(cls, value: object) -> str | None:
        return normalize_doi(None if value is None else str(value))

    @field_validator("arxiv_id", mode="before")
    @classmethod
    def _arxiv(cls, value: object) -> str | None:
        return normalize_arxiv_id(None if value is None else str(value))

    @field_validator("source_platforms", mode="before")
    @classmethod
    def _platforms(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("source_platforms must be a sequence")
        platforms = tuple(dict.fromkeys(_validate_source_id(str(item), "source_platforms") for item in value))
        if not platforms:
            raise ValueError("source_platforms must be non-empty")
        return platforms

    @field_validator("source_records", mode="before")
    @classmethod
    def _source_records(cls, value: object) -> tuple[object, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("source_records must be a sequence")
        return tuple(value)

    @field_validator("landing_urls", mode="before")
    @classmethod
    def _landing_urls(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("landing_urls must be a sequence")
        return tuple(dict.fromkeys(sanitize_public_https_url(str(item), field_name="landing_urls") for item in value))

    @field_validator("merged_from_candidate_ids", mode="before")
    @classmethod
    def _merged_ids(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("merged_from_candidate_ids must be a sequence")
        return tuple(dict.fromkeys(_validate_id(str(item), "merged_from_candidate_ids") for item in value))

    @field_validator("published_date", "abstract")
    @classmethod
    def _optional_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        normalized = _validate_safe_text(value, _validation_field_name(info))
        return normalized or None

    @field_validator("created_at", "updated_at")
    @classmethod
    def _timestamps(cls, value: datetime, info: ValidationInfo) -> datetime:
        return _validate_aware_timestamp(value, _validation_field_name(info))

    @model_validator(mode="after")
    def _candidate_shape(self) -> "CandidateManifest":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        source_record_keys = [
            (record.source_platform, record.source_record_id, record.source_revision)
            for record in self.source_records
        ]
        if len(source_record_keys) != len(set(source_record_keys)):
            raise ValueError("source_records must not repeat one source revision")
        if any(record.source_platform not in self.source_platforms for record in self.source_records):
            raise ValueError("source record platform must appear in source_platforms")
        for pdf in self.pdf_candidates:
            if pdf.access_evidence.candidate_id not in {self.candidate_id, *self.merged_from_candidate_ids}:
                raise ValueError("PDF access evidence must belong to this merged candidate")
            if pdf.source_platform not in self.source_platforms:
                raise ValueError("PDF source must appear in source_platforms")
        return self


class SourceError(StrictRecord):
    """Bounded source-specific search failure."""

    source_id: str
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)

    @field_validator("source_id")
    @classmethod
    def _source(cls, value: str) -> str:
        return _validate_source_id(value, "source_id")

    @field_validator("code")
    @classmethod
    def _code(cls, value: str) -> str:
        return _validate_id(value, "code")

    @field_validator("message")
    @classmethod
    def _message(cls, value: str) -> str:
        normalized = _validate_safe_text(value, "message")
        if not normalized:
            raise ValueError("message must be non-empty")
        return normalized


class SearchRun(StrictRecord):
    """Persisted result of one explicit multi-source search."""

    run_id: str
    query: SearchQuery
    status: SearchRunStatus = SearchRunStatus.CREATED
    requested_sources: tuple[str, ...]
    attempted_sources: tuple[str, ...] = ()
    candidates: tuple[CandidateManifest, ...] = Field(default=(), max_length=MAX_CANDIDATES_PER_RUN)
    source_errors: tuple[SourceError, ...] = Field(default=(), max_length=MAX_SOURCE_ERRORS)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None

    @field_validator("run_id")
    @classmethod
    def _run_id(cls, value: str) -> str:
        return _validate_id(value, "run_id")

    @field_validator("requested_sources", "attempted_sources", mode="before")
    @classmethod
    def _sources(cls, value: object, info: ValidationInfo) -> tuple[str, ...]:
        field_name = _validation_field_name(info)
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{field_name} must be a sequence")
        return tuple(dict.fromkeys(_validate_source_id(str(item), field_name) for item in value))

    @field_validator("created_at", "updated_at", "completed_at")
    @classmethod
    def _timestamps(cls, value: datetime | None, info: ValidationInfo) -> datetime | None:
        if value is None:
            return None
        return _validate_aware_timestamp(value, _validation_field_name(info))

    @model_validator(mode="after")
    def _run_shape(self) -> "SearchRun":
        if self.query.sources != self.requested_sources:
            raise ValueError("requested_sources must match query.sources")
        if any(source not in self.requested_sources for source in self.attempted_sources):
            raise ValueError("attempted_sources must be requested")
        if any(candidate.run_id != self.run_id for candidate in self.candidates):
            raise ValueError("candidate run_id must match SearchRun")
        if any(candidate.project_id != self.query.project_id for candidate in self.candidates):
            raise ValueError("candidate project_id must match SearchQuery")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        terminal = self.status in {SearchRunStatus.COMPLETED, SearchRunStatus.PARTIAL, SearchRunStatus.FAILED}
        if terminal != (self.completed_at is not None):
            raise ValueError("terminal search runs require completed_at")
        return self


class IdentityMergeReceipt(StrictRecord):
    """Audit record for one deterministic candidate identity decision."""

    merge_id: str
    run_id: str
    project_id: str
    canonical_candidate_id: str
    compared_candidate_id: str
    outcome: IdentityDecisionOutcome
    method: IdentityMatchMethod
    merged: bool
    evidence: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_IDENTITY_EVIDENCE_ITEMS,
    )
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator(
        "merge_id",
        "run_id",
        "project_id",
        "canonical_candidate_id",
        "compared_candidate_id",
    )
    @classmethod
    def _ids(cls, value: str, info: ValidationInfo) -> str:
        return _validate_id(value, _validation_field_name(info))

    @field_validator("evidence", mode="before")
    @classmethod
    def _evidence(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("evidence must be a sequence")
        evidence = tuple(
            dict.fromkeys(
                item
                for item in (_validate_safe_text(str(raw), "evidence") for raw in value)
                if item
            )
        )
        if not evidence:
            raise ValueError("evidence must be non-empty")
        return evidence

    @field_validator("created_at")
    @classmethod
    def _created(cls, value: datetime) -> datetime:
        return _validate_aware_timestamp(value, "created_at")

    @model_validator(mode="after")
    def _decision(self) -> "IdentityMergeReceipt":
        if self.canonical_candidate_id == self.compared_candidate_id:
            raise ValueError("identity decision endpoints must be different")
        expected_merged = self.outcome is IdentityDecisionOutcome.MATCH
        if self.merged != expected_merged:
            raise ValueError("identity outcome and merged flag disagree")
        if expected_merged != (self.method is not IdentityMatchMethod.DISTINCT):
            raise ValueError("identity outcome and match method disagree")
        return self


class CandidateVersionRelation(StrictRecord):
    """Persisted directed relation between two retained candidate versions."""

    relation_id: str
    run_id: str
    project_id: str
    source_candidate_id: str
    target_candidate_id: str
    relation: VersionRelationType
    evidence_kind: VersionRelationEvidenceKind
    evidence: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_IDENTITY_EVIDENCE_ITEMS,
    )
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator(
        "relation_id",
        "run_id",
        "project_id",
        "source_candidate_id",
        "target_candidate_id",
    )
    @classmethod
    def _ids(cls, value: str, info: ValidationInfo) -> str:
        return _validate_id(value, _validation_field_name(info))

    @field_validator("evidence", mode="before")
    @classmethod
    def _evidence(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("evidence must be a sequence")
        evidence = tuple(
            dict.fromkeys(
                item
                for item in (_validate_safe_text(str(raw), "evidence") for raw in value)
                if item
            )
        )
        if not evidence:
            raise ValueError("evidence must be non-empty")
        return evidence

    @field_validator("created_at")
    @classmethod
    def _created(cls, value: datetime) -> datetime:
        return _validate_aware_timestamp(value, "created_at")

    @model_validator(mode="after")
    def _relation_shape(self) -> "CandidateVersionRelation":
        if self.source_candidate_id == self.target_candidate_id:
            raise ValueError("version relation endpoints must be different")
        expected_kind = {
            VersionRelationType.REVISION_OF: VersionRelationEvidenceKind.SOURCE_REVISION,
            VersionRelationType.PREPRINT_OF: VersionRelationEvidenceKind.DOI_AND_SOURCE_STAGE,
        }[self.relation]
        if self.evidence_kind is not expected_kind:
            raise ValueError("version relation and evidence kind disagree")
        return self


class HumanAccessGate(StrictRecord):
    """User-owned browser/access gate; automatic workers must stop here."""

    gate_id: str
    project_id: str
    job_id: str | None = None
    platform: str
    gate_type: Literal[
        "login",
        "captcha",
        "paywall",
        "robots",
        "sso",
        "two_factor",
        "cloudflare",
        "http_401",
        "http_403",
        "http_407",
        "http_429",
        "http_503",
        "html_instead_of_pdf",
    ]
    url: str
    message: str = Field(min_length=1, max_length=500)
    status: GateStatus = GateStatus.OPEN
    resume_status: DownloadJobStatus = DownloadJobStatus.QUEUED
    next_action: str = Field(min_length=1, max_length=500)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None

    @field_validator("gate_id", "project_id", "job_id")
    @classmethod
    def _ids(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        return _validate_id(value, _validation_field_name(info))

    @field_validator("platform")
    @classmethod
    def _platform(cls, value: str) -> str:
        return _validate_source_id(value, "platform")

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        return sanitize_public_https_url(value, field_name="gate.url")

    @field_validator("message", "next_action")
    @classmethod
    def _text(cls, value: str, info: ValidationInfo) -> str:
        field_name = _validation_field_name(info)
        normalized = _validate_safe_text(value, field_name)
        if not normalized:
            raise ValueError(f"{field_name} must be non-empty")
        return normalized

    @field_validator("created_at", "updated_at", "resolved_at")
    @classmethod
    def _times(cls, value: datetime | None, info: ValidationInfo) -> datetime | None:
        if value is None:
            return None
        return _validate_aware_timestamp(value, _validation_field_name(info))

    @model_validator(mode="after")
    def _gate_shape(self) -> "HumanAccessGate":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.status is GateStatus.OPEN and self.resolved_at is not None:
            raise ValueError("open gate cannot have resolved_at")
        if self.status is GateStatus.RESOLVED and self.resolved_at is None:
            raise ValueError("resolved gate requires resolved_at")
        return self


class DownloadJob(StrictRecord):
    """Persisted, resumable download intent and lifecycle."""

    job_id: str
    project_id: str
    candidate_id: str
    access_evidence_id: str
    source_platform: str
    source_url: str
    artifact_path: str
    status: DownloadJobStatus = DownloadJobStatus.QUEUED
    attempts: int = Field(default=0, ge=0, le=100)
    bytes_downloaded: int = Field(default=0, ge=0)
    max_bytes: int = Field(default=100 * 1024 * 1024, ge=4096, le=1024 * 1024 * 1024)
    version: int = Field(default=1, ge=1)
    error_code: str | None = Field(default=None, max_length=80)
    error_message: str | None = Field(default=None, max_length=500)
    gate_id: str | None = None
    artifact_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @field_validator(
        "job_id",
        "project_id",
        "candidate_id",
        "access_evidence_id",
        "gate_id",
        "artifact_id",
    )
    @classmethod
    def _ids(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        return _validate_id(value, _validation_field_name(info))

    @field_validator("source_platform")
    @classmethod
    def _platform(cls, value: str) -> str:
        return _validate_source_id(value, "source_platform")

    @field_validator("source_url")
    @classmethod
    def _source_url(cls, value: str) -> str:
        return sanitize_public_https_url(value, field_name="source_url")

    @field_validator("artifact_path")
    @classmethod
    def _artifact_path(cls, value: str) -> str:
        return normalize_relative_artifact_path(value)

    @field_validator("error_code")
    @classmethod
    def _error_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_id(value, "error_code")

    @field_validator("error_message")
    @classmethod
    def _error_message(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _validate_safe_text(value, "error_message")
        return normalized or None

    @field_validator("created_at", "updated_at", "started_at", "completed_at")
    @classmethod
    def _times(cls, value: datetime | None, info: ValidationInfo) -> datetime | None:
        if value is None:
            return None
        return _validate_aware_timestamp(value, _validation_field_name(info))

    @model_validator(mode="after")
    def _job_shape(self) -> "DownloadJob":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.status is DownloadJobStatus.HUMAN_REQUIRED and self.gate_id is None:
            raise ValueError("human_required download requires gate_id")
        if self.status is DownloadJobStatus.COMPLETED:
            if self.artifact_id is None or self.completed_at is None:
                raise ValueError("completed download requires artifact_id and completed_at")
        elif self.completed_at is not None:
            raise ValueError("only completed downloads may set completed_at")
        return self


class AcquisitionAttempt(StrictRecord):
    """Append-only evidence for one source search or download invocation."""

    attempt_id: str
    project_id: str
    run_id: str | None = None
    job_id: str | None = None
    source_id: str
    stage: AcquisitionAttemptStage
    outcome: AcquisitionAttemptOutcome
    ordinal: int = Field(ge=1, le=1000)
    result_count: int | None = Field(default=None, ge=0, le=MAX_CANDIDATES_PER_RUN)
    http_status: int | None = Field(default=None, ge=100, le=599)
    error_class: str | None = Field(default=None, max_length=80)
    error_message: str | None = Field(default=None, max_length=500)
    elapsed_ms: int = Field(default=0, ge=0, le=86_400_000)
    gate_id: str | None = None
    retryable: bool = False
    next_action: str | None = Field(default=None, max_length=500)
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime = Field(default_factory=utc_now)

    @field_validator("attempt_id", "project_id", "run_id", "job_id", "gate_id")
    @classmethod
    def _ids(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        return _validate_id(value, _validation_field_name(info))

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return _validate_source_id(value, "source_id")

    @field_validator("error_class")
    @classmethod
    def _error_class(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_id(value, "error_class")

    @field_validator("error_message", "next_action")
    @classmethod
    def _safe_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        normalized = _validate_safe_text(value, _validation_field_name(info))
        return normalized or None

    @field_validator("started_at", "finished_at")
    @classmethod
    def _times(cls, value: datetime, info: ValidationInfo) -> datetime:
        return _validate_aware_timestamp(value, _validation_field_name(info))

    @model_validator(mode="after")
    def _attempt_shape(self) -> "AcquisitionAttempt":
        if (self.run_id is None) == (self.job_id is None):
            raise ValueError("acquisition attempt requires exactly one run_id or job_id")
        if self.stage is AcquisitionAttemptStage.SEARCH and self.run_id is None:
            raise ValueError("search attempt requires run_id")
        if self.stage is AcquisitionAttemptStage.DOWNLOAD and self.job_id is None:
            raise ValueError("download attempt requires job_id")
        if self.outcome is AcquisitionAttemptOutcome.HUMAN_REQUIRED:
            if self.gate_id is None or self.next_action is None:
                raise ValueError("human-required attempt requires gate_id and next_action")
        if self.outcome is AcquisitionAttemptOutcome.FAILED and self.error_class is None:
            raise ValueError("failed attempt requires error_class")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        return self


class PdfValidationProvenance(StrictRecord):
    """Exact validator and parser facts bound to promoted PDF bytes."""

    validator_id: str
    validator_version: str = Field(min_length=1, max_length=80)
    parser_id: str
    parser_version: str = Field(min_length=1, max_length=80)
    checks: tuple[
        Literal["size", "pdf_magic", "pdf_eof", "parser_readable", "sha256"],
        ...,
    ]
    validated_at: datetime = Field(default_factory=utc_now)

    @field_validator("validator_id", "parser_id")
    @classmethod
    def _component_ids(cls, value: str, info: ValidationInfo) -> str:
        return _validate_source_id(value, _validation_field_name(info))

    @field_validator("validator_version", "parser_version")
    @classmethod
    def _versions(cls, value: str, info: ValidationInfo) -> str:
        field_name = _validation_field_name(info)
        normalized = _validate_safe_text(value, field_name)
        if not normalized:
            raise ValueError(f"{field_name} must be non-empty")
        return normalized

    @field_validator("checks")
    @classmethod
    def _checks(
        cls,
        value: tuple[Literal["size", "pdf_magic", "pdf_eof", "parser_readable", "sha256"], ...],
    ) -> tuple[Literal["size", "pdf_magic", "pdf_eof", "parser_readable", "sha256"], ...]:
        required = ("size", "pdf_magic", "pdf_eof", "parser_readable", "sha256")
        if value != required:
            raise ValueError("checks must contain the complete ordered PDF validation contract")
        return value

    @field_validator("validated_at")
    @classmethod
    def _validated_at(cls, value: datetime) -> datetime:
        return _validate_aware_timestamp(value, "validated_at")


class ArtifactPromotionProof(StrictRecord):
    """Durable authorization and validation proof recorded before file promotion."""

    proof_id: str
    artifact_id: str
    job_id: str
    attempt_id: str
    project_id: str
    candidate_id: str
    source_platform: str
    source_url: str
    final_url: str
    access_evidence: AccessEvidence
    relative_path: str
    size_bytes: int = Field(ge=4096)
    sha256: str = Field(min_length=64, max_length=64)
    page_count: int = Field(ge=1)
    validation: PdfValidationProvenance
    state: ArtifactPromotionState = ArtifactPromotionState.PREPARED
    version: int = Field(default=1, ge=1)
    prepared_at: datetime = Field(default_factory=utc_now)
    promoted_at: datetime | None = None

    @field_validator("proof_id", "artifact_id", "job_id", "attempt_id", "project_id", "candidate_id")
    @classmethod
    def _ids(cls, value: str, info: ValidationInfo) -> str:
        return _validate_id(value, _validation_field_name(info))

    @field_validator("source_platform")
    @classmethod
    def _platform(cls, value: str) -> str:
        return _validate_source_id(value, "source_platform")

    @field_validator("source_url", "final_url")
    @classmethod
    def _urls(cls, value: str, info: ValidationInfo) -> str:
        return sanitize_public_https_url(value, field_name=_validation_field_name(info))

    @field_validator("relative_path")
    @classmethod
    def _path(cls, value: str) -> str:
        normalized = normalize_relative_artifact_path(value)
        if not normalized.lower().endswith(".pdf"):
            raise ValueError("promotion proof must target a PDF")
        return normalized

    @field_validator("sha256")
    @classmethod
    def _sha256(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("sha256 must contain 64 lowercase hex characters")
        return normalized

    @field_validator("prepared_at", "promoted_at")
    @classmethod
    def _promotion_times(cls, value: datetime | None, info: ValidationInfo) -> datetime | None:
        if value is None:
            return None
        return _validate_aware_timestamp(value, _validation_field_name(info))

    @model_validator(mode="after")
    def _proof_shape(self) -> "ArtifactPromotionProof":
        evidence = self.access_evidence
        if (
            evidence.candidate_id != self.candidate_id
            or evidence.source_platform != self.source_platform
            or evidence.pdf_url != self.source_url
        ):
            raise ValueError("promotion proof does not match its AccessEvidence")
        if self.prepared_at < self.validation.validated_at:
            raise ValueError("prepared_at must not precede validation")
        if self.state is ArtifactPromotionState.PREPARED:
            if self.version != 1 or self.promoted_at is not None:
                raise ValueError("prepared proof requires version 1 without promoted_at")
        elif self.promoted_at is None or self.promoted_at < self.prepared_at:
            raise ValueError("promoted proof requires a promotion time after preparation")
        return self


class ValidatedArtifact(StrictRecord):
    """Validated immutable PDF ready for existing-project ingestion."""

    artifact_id: str
    job_id: str
    project_id: str
    candidate_id: str
    relative_path: str
    size_bytes: int = Field(ge=4096)
    sha256: str = Field(min_length=64, max_length=64)
    media_type: Literal["application/pdf"] = "application/pdf"
    page_count: int = Field(ge=1)
    validated_at: datetime = Field(default_factory=utc_now)

    @field_validator("artifact_id", "job_id", "project_id", "candidate_id")
    @classmethod
    def _ids(cls, value: str, info: ValidationInfo) -> str:
        return _validate_id(value, _validation_field_name(info))

    @field_validator("relative_path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        normalized = normalize_relative_artifact_path(value)
        if not normalized.lower().endswith(".pdf"):
            raise ValueError("validated artifact must be a PDF")
        return normalized

    @field_validator("sha256")
    @classmethod
    def _sha256(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("sha256 must contain 64 lowercase hex characters")
        return normalized

    @field_validator("validated_at")
    @classmethod
    def _validated_at(cls, value: datetime) -> datetime:
        return _validate_aware_timestamp(value, "validated_at")


class ImportPublicationEvidence(StrictRecord):
    """Strict proof that one material is fully published and retrieval-visible."""

    schema_version: Literal["scholar-ai-import-publication-evidence/v1"] = (
        "scholar-ai-import-publication-evidence/v1"
    )
    verifier_version: Literal["scholar-ai-material-publication-verifier/v1"] = (
        "scholar-ai-material-publication-verifier/v1"
    )
    project_id: str
    material_id: str
    source_fingerprint: str = Field(min_length=71, max_length=71)
    source_size_bytes: int = Field(ge=4096, le=1_099_511_627_776)
    document_content_sha256: str = Field(min_length=71, max_length=71)
    chunk_manifest_version: Literal[2] = 2
    chunk_manifest_sha256: str = Field(min_length=71, max_length=71)
    chunk_hash_version: str = Field(min_length=1, max_length=128)
    material_chunk_file_sha256: str = Field(min_length=71, max_length=71)
    material_chunk_count: int = Field(ge=1, le=10_000_000)
    material_chunk_root_sha256: str = Field(min_length=71, max_length=71)
    chunk_store_version: str = Field(min_length=64, max_length=64)
    fts_schema_version: str = Field(min_length=1, max_length=128)
    fts_chunk_store_version: str = Field(min_length=64, max_length=64)
    fts_indexed_count: int = Field(ge=1, le=100_000_000)
    fts_skipped_count: int = Field(ge=0, le=100_000_000)
    fts_material_indexed_count: int = Field(ge=1, le=10_000_000)
    revision_fingerprint: str = Field(min_length=71, max_length=71)
    revision_receipt_id: str
    revision_applied_at: datetime
    verified_at: datetime = Field(default_factory=utc_now)
    evidence_fingerprint: str = ""

    @field_validator("project_id", "material_id", "revision_receipt_id")
    @classmethod
    def _ids(cls, value: str, info: ValidationInfo) -> str:
        return _validate_id(value, _validation_field_name(info))

    @field_validator(
        "source_fingerprint",
        "document_content_sha256",
        "chunk_manifest_sha256",
        "material_chunk_file_sha256",
        "material_chunk_root_sha256",
        "revision_fingerprint",
    )
    @classmethod
    def _prefixed_sha256(cls, value: str, info: ValidationInfo) -> str:
        normalized = str(value or "").strip().lower()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", normalized):
            raise ValueError(f"{_validation_field_name(info)} must use sha256:<64 lowercase hex>")
        return normalized

    @field_validator("chunk_store_version", "fts_chunk_store_version")
    @classmethod
    def _plain_sha256(cls, value: str, info: ValidationInfo) -> str:
        normalized = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError(f"{_validation_field_name(info)} must contain 64 lowercase hex characters")
        return normalized

    @field_validator("chunk_hash_version", "fts_schema_version")
    @classmethod
    def _contract_versions(cls, value: str, info: ValidationInfo) -> str:
        field_name = _validation_field_name(info)
        normalized = _validate_safe_text(value, field_name)
        if not normalized:
            raise ValueError(f"{field_name} must be non-empty")
        return normalized

    @field_validator("revision_applied_at", "verified_at")
    @classmethod
    def _times(cls, value: datetime, info: ValidationInfo) -> datetime:
        return _validate_aware_timestamp(value, _validation_field_name(info))

    @field_validator("evidence_fingerprint")
    @classmethod
    def _evidence_fingerprint_shape(cls, value: str) -> str:
        if not value:
            return ""
        normalized = str(value).strip().lower()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", normalized):
            raise ValueError("evidence_fingerprint must use sha256:<64 lowercase hex>")
        return normalized

    @model_validator(mode="after")
    def _evidence_shape(self) -> "ImportPublicationEvidence":
        if self.fts_chunk_store_version != self.chunk_store_version:
            raise ValueError("FTS index must bind the verified chunk-store version")
        if self.fts_material_indexed_count != self.material_chunk_count:
            raise ValueError("all verified material chunks must be present in the FTS index")
        if self.fts_indexed_count < self.fts_material_indexed_count:
            raise ValueError("global FTS row count cannot be smaller than the material row count")
        if self.verified_at < self.revision_applied_at:
            raise ValueError("verified_at must not precede the applied material revision")
        payload = self.model_dump(mode="json", exclude={"evidence_fingerprint"})
        computed = "sha256:" + hashlib.sha256(
            json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if self.evidence_fingerprint and self.evidence_fingerprint != computed:
            raise ValueError("evidence_fingerprint does not match publication evidence")
        object.__setattr__(self, "evidence_fingerprint", computed)
        return self


class ImportReceipt(StrictRecord):
    """Durable link from a validated artifact to the existing material path."""

    receipt_id: str
    artifact_id: str
    project_id: str
    candidate_id: str
    material_id: str
    status: ImportStatus
    source_fingerprint: str = Field(min_length=71, max_length=71)
    receipt_schema_version: Literal[
        "scholar-ai-import-receipt/v1",
        "scholar-ai-import-receipt/v2",
    ] = "scholar-ai-import-receipt/v1"
    publication_state: ImportPublicationState = ImportPublicationState.UNVERIFIED_LEGACY
    publication_evidence: ImportPublicationEvidence | None = None
    runtime_session_id: str | None = None
    runtime_job_id: str | None = None
    open_url: str
    error_message: str | None = Field(default=None, max_length=500)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator(
        "receipt_id",
        "artifact_id",
        "project_id",
        "candidate_id",
        "material_id",
        "runtime_session_id",
        "runtime_job_id",
    )
    @classmethod
    def _ids(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        return _validate_id(value, _validation_field_name(info))

    @field_validator("source_fingerprint")
    @classmethod
    def _fingerprint(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", normalized):
            raise ValueError("source_fingerprint must use sha256:<64 lowercase hex>")
        return normalized

    @field_validator("open_url")
    @classmethod
    def _open_url(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not re.fullmatch(r"/workbench/paper/[A-Za-z0-9._:@+-]{1,256}", normalized):
            raise ValueError("open_url must be a local material route")
        return normalized

    @field_validator("error_message")
    @classmethod
    def _error(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _validate_safe_text(value, "error_message")
        return normalized or None

    @field_validator("created_at", "updated_at")
    @classmethod
    def _times(cls, value: datetime, info: ValidationInfo) -> datetime:
        return _validate_aware_timestamp(value, _validation_field_name(info))

    @model_validator(mode="after")
    def _receipt_shape(self) -> "ImportReceipt":
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.status is ImportStatus.QUEUED and (self.runtime_job_id is None or self.runtime_session_id is None):
            raise ValueError("queued import requires runtime job and session ids")
        if self.receipt_schema_version == "scholar-ai-import-receipt/v1":
            if (
                self.publication_state is not ImportPublicationState.UNVERIFIED_LEGACY
                or self.publication_evidence is not None
            ):
                raise ValueError("legacy import receipts cannot claim publication verification")
            return self

        allowed_states = {
            ImportStatus.QUEUED: frozenset({ImportPublicationState.PENDING}),
            ImportStatus.FAILED: frozenset({ImportPublicationState.FAILED}),
            ImportStatus.COMPLETED: frozenset(
                {ImportPublicationState.PENDING, ImportPublicationState.VERIFIED}
            ),
            ImportStatus.DUPLICATE: frozenset(
                {ImportPublicationState.PENDING, ImportPublicationState.VERIFIED}
            ),
        }[self.status]
        if self.publication_state not in allowed_states:
            raise ValueError("receipt status does not match publication state")
        if self.publication_state is ImportPublicationState.VERIFIED:
            evidence = self.publication_evidence
            if evidence is None:
                raise ValueError("verified import receipt requires publication evidence")
            if (
                evidence.project_id != self.project_id
                or evidence.material_id != self.material_id
                or evidence.source_fingerprint != self.source_fingerprint
            ):
                raise ValueError("publication evidence does not match the import receipt")
        elif self.publication_evidence is not None:
            raise ValueError("unverified import receipt cannot contain publication evidence")
        return self


def _source_revision_number(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.fullmatch(r"v(\d+)", value, flags=re.IGNORECASE)
    if match is None:
        return None
    return int(match.group(1))


def _explicit_revision_relation(
    left: CandidateManifest,
    right: CandidateManifest,
) -> tuple[CandidateManifest, CandidateManifest, tuple[str, ...]] | None:
    decisions: list[tuple[str, str, str]] = []
    for left_record in left.source_records:
        left_revision = _source_revision_number(left_record.source_revision)
        if left_revision is None:
            continue
        for right_record in right.source_records:
            right_revision = _source_revision_number(right_record.source_revision)
            if (
                right_revision is None
                or left_record.source_platform != right_record.source_platform
                or left_record.source_record_id != right_record.source_record_id
                or left_revision == right_revision
            ):
                continue
            source_id = left.candidate_id if left_revision > right_revision else right.candidate_id
            target_id = right.candidate_id if left_revision > right_revision else left.candidate_id
            newer = left_record.source_revision if left_revision > right_revision else right_record.source_revision
            older = right_record.source_revision if left_revision > right_revision else left_record.source_revision
            decisions.append(
                (
                    source_id,
                    target_id,
                    f"source_revision:{left_record.source_platform}:{left_record.source_record_id}:{newer}->{older}",
                )
            )
    if not decisions:
        return None
    orientations = {(source_id, target_id) for source_id, target_id, _ in decisions}
    if len(orientations) != 1:
        return None
    source_id, target_id = next(iter(orientations))
    source = left if left.candidate_id == source_id else right
    target = left if left.candidate_id == target_id else right
    evidence = tuple(dict.fromkeys(item[2] for item in decisions))[:MAX_IDENTITY_EVIDENCE_ITEMS]
    return source, target, evidence


def _explicit_preprint_relation(
    left: CandidateManifest,
    right: CandidateManifest,
) -> tuple[CandidateManifest, CandidateManifest, tuple[str, ...]] | None:
    if left.doi is None or left.doi != right.doi:
        return None
    left_stages = {
        record.publication_stage
        for record in left.source_records
        if record.publication_stage is not PublicationStage.UNKNOWN
    }
    right_stages = {
        record.publication_stage
        for record in right.source_records
        if record.publication_stage is not PublicationStage.UNKNOWN
    }
    if left_stages == {PublicationStage.PREPRINT} and right_stages == {PublicationStage.PUBLISHED}:
        preprint, published = left, right
    elif left_stages == {PublicationStage.PUBLISHED} and right_stages == {PublicationStage.PREPRINT}:
        preprint, published = right, left
    else:
        return None
    return (
        preprint,
        published,
        (f"shared_doi:{left.doi}", "source_stages:preprint->published"),
    )


def candidate_identity_match(
    left: CandidateManifest,
    right: CandidateManifest,
) -> IdentityMatchMethod:
    """Return the strongest deterministic identity relation between candidates.

    Conflicting non-empty DOI or arXiv identifiers always keep records distinct.
    Title fallback requires a known equal year and at least one conservatively
    matching full author name; missing authors and surname-only similarities
    are never treated as identity evidence.
    """

    if _explicit_revision_relation(left, right) is not None:
        return IdentityMatchMethod.DISTINCT
    if _explicit_preprint_relation(left, right) is not None:
        return IdentityMatchMethod.DISTINCT
    if left.doi and right.doi and left.doi != right.doi:
        return IdentityMatchMethod.DISTINCT
    if left.arxiv_id and right.arxiv_id and left.arxiv_id != right.arxiv_id:
        return IdentityMatchMethod.DISTINCT
    if left.doi and right.doi:
        return IdentityMatchMethod.DOI
    if left.arxiv_id and right.arxiv_id:
        return IdentityMatchMethod.ARXIV_ID
    author_overlap = _author_identity_keys(left.authors) & _author_identity_keys(right.authors)
    if (
        left.year is not None
        and left.year == right.year
        and normalize_title(left.title) == normalize_title(right.title)
        and author_overlap
    ):
        return IdentityMatchMethod.TITLE_YEAR
    return IdentityMatchMethod.DISTINCT


def candidate_identity_evidence(
    left: CandidateManifest,
    right: CandidateManifest,
    method: IdentityMatchMethod,
) -> tuple[str, ...]:
    """Return bounded, deterministic evidence for one identity decision."""

    revision = _explicit_revision_relation(left, right)
    if revision is not None:
        return revision[2]
    preprint = _explicit_preprint_relation(left, right)
    if preprint is not None:
        return preprint[2]
    if method is IdentityMatchMethod.DOI and left.doi is not None:
        return (f"shared_doi:{left.doi}",)
    if method is IdentityMatchMethod.ARXIV_ID and left.arxiv_id is not None:
        return (f"shared_arxiv_id:{left.arxiv_id}",)
    if method is IdentityMatchMethod.TITLE_YEAR:
        title_hash = hashlib.sha256(normalize_title(left.title).encode("utf-8")).hexdigest()
        return (f"title_year_author_match:{left.year}", f"normalized_title_sha256:{title_hash}")
    if left.doi and right.doi and left.doi != right.doi:
        return (f"conflicting_doi:{left.doi}|{right.doi}",)
    if left.arxiv_id and right.arxiv_id and left.arxiv_id != right.arxiv_id:
        return (f"conflicting_arxiv_id:{left.arxiv_id}|{right.arxiv_id}",)
    return ("no_deterministic_identity_signal",)


def build_explicit_version_relation(
    left: CandidateManifest,
    right: CandidateManifest,
    *,
    created_at: datetime | None = None,
) -> CandidateVersionRelation | None:
    """Build one conservative directed version relation, or return ``None``.

    Revision edges require the same source record plus two ordered ``vN``
    revisions. Preprint edges require both a shared DOI and explicit, opposing
    source stages. Titles are deliberately not version evidence.
    """

    if left.run_id != right.run_id or left.project_id != right.project_id:
        raise ValueError("version relation candidates must belong to the same run and project")
    revision = _explicit_revision_relation(left, right)
    if revision is not None:
        source, target, evidence = revision
        relation = VersionRelationType.REVISION_OF
        evidence_kind = VersionRelationEvidenceKind.SOURCE_REVISION
    else:
        preprint = _explicit_preprint_relation(left, right)
        if preprint is None:
            return None
        source, target, evidence = preprint
        relation = VersionRelationType.PREPRINT_OF
        evidence_kind = VersionRelationEvidenceKind.DOI_AND_SOURCE_STAGE
    seed = "\0".join(
        (
            left.run_id,
            relation.value,
            source.candidate_id,
            target.candidate_id,
            evidence_kind.value,
        )
    ).encode("utf-8")
    return CandidateVersionRelation(
        relation_id=f"version_{hashlib.sha256(seed).hexdigest()[:24]}",
        run_id=left.run_id,
        project_id=left.project_id,
        source_candidate_id=source.candidate_id,
        target_candidate_id=target.candidate_id,
        relation=relation,
        evidence_kind=evidence_kind,
        evidence=evidence,
        created_at=created_at or utc_now(),
    )


def merge_candidate_manifests(
    canonical: CandidateManifest,
    incoming: CandidateManifest,
) -> tuple[CandidateManifest, IdentityMatchMethod]:
    """Merge two matching manifests while retaining source/evidence provenance."""

    method = candidate_identity_match(canonical, incoming)
    if method is IdentityMatchMethod.DISTINCT:
        raise ValueError("candidate manifests do not share a mergeable identity")
    if canonical.project_id != incoming.project_id or canonical.run_id != incoming.run_id:
        raise ValueError("candidate manifests must belong to the same run and project")

    pdf_by_url = {item.pdf_url: item for item in canonical.pdf_candidates}
    for item in incoming.pdf_candidates:
        pdf_by_url.setdefault(item.pdf_url, item)
    source_records = {
        (record.source_platform, record.source_record_id, record.source_revision): record
        for record in canonical.source_records
    }
    for record in incoming.source_records:
        key = (record.source_platform, record.source_record_id, record.source_revision)
        existing = source_records.get(key)
        if existing is None or existing.publication_stage is PublicationStage.UNKNOWN:
            source_records[key] = record
        elif (
            record.publication_stage is not PublicationStage.UNKNOWN
            and existing.publication_stage is not record.publication_stage
        ):
            raise ValueError("matching source record has conflicting publication stages")
    now = utc_now()
    merged = canonical.model_copy(
        update={
            "title": canonical.title if len(canonical.title) >= len(incoming.title) else incoming.title,
            "authors": tuple(dict.fromkeys((*canonical.authors, *incoming.authors))),
            "year": canonical.year if canonical.year is not None else incoming.year,
            "published_date": canonical.published_date or incoming.published_date,
            "abstract": canonical.abstract or incoming.abstract,
            "doi": canonical.doi or incoming.doi,
            "arxiv_id": canonical.arxiv_id or incoming.arxiv_id,
            "source_platforms": tuple(dict.fromkeys((*canonical.source_platforms, *incoming.source_platforms))),
            "source_records": tuple(source_records.values()),
            "landing_urls": tuple(dict.fromkeys((*canonical.landing_urls, *incoming.landing_urls))),
            "pdf_candidates": tuple(pdf_by_url.values()),
            "merged_from_candidate_ids": tuple(
                dict.fromkeys(
                    (*canonical.merged_from_candidate_ids, incoming.candidate_id, *incoming.merged_from_candidate_ids)
                )
            ),
            "updated_at": now,
        }
    )
    return CandidateManifest.model_validate(merged.model_dump(mode="python")), method


def semantic_digest(record: BaseModel) -> str:
    """Return a stable SHA-256 digest for one validated acquisition record."""

    payload = record.model_dump(
        mode="json",
        exclude={"created_at", "updated_at", "validated_at", "version"},
    )
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
