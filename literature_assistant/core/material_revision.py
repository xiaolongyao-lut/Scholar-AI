"""Durable material revision identities and downstream-sync receipts.

This module is deliberately independent from ingestion, citation, visual, Wiki,
and graph stores.  It records what revision was observed, which revision is the
currently applied head, and whether caller-owned downstream synchronization has
finished.  It does not perform that synchronization itself.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

MATERIAL_REVISION_STORE_SCHEMA_VERSION = 1
MAX_MATERIAL_REVISION_LIST_LIMIT = 200

MaterialComponentKind = Literal["parser", "extractor", "ocr", "chunker"]
MaterialRevisionValueState = Literal[
    "known",
    "unknown",
    "unavailable",
    "not_applicable",
]
MaterialSyncComponent = Literal["citation", "visual", "reviewed"]
MaterialSyncProgressStatus = Literal["pending", "applied"]
MaterialSyncProgressOutcome = Literal["applied", "no_op"]
MaterialSyncReceiptStatus = Literal["pending", "applied", "failed"]

MATERIAL_SYNC_COMPONENTS: tuple[MaterialSyncComponent, ...] = (
    "citation",
    "visual",
    "reviewed",
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_COMPONENT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:+/@-]{0,127}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:+/@-]{0,127}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ERROR_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_:-]{0,95}$")


class MaterialRevisionStoreError(RuntimeError):
    """Base error for material revision persistence failures."""


class MaterialRevisionConflictError(MaterialRevisionStoreError):
    """Raised when a CAS, replay, or active-transition precondition fails."""


class MaterialRevisionNotFoundError(MaterialRevisionStoreError):
    """Raised when a requested durable receipt does not exist."""


class MaterialRevisionCorruptionError(MaterialRevisionStoreError):
    """Raised when persisted material revision data violates its contract."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _ID_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} has an unsupported identifier shape")
    return normalized


def _validate_sha256(value: str, field_name: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must use sha256:<64 lowercase hex>")
    return normalized


def _validate_optional_sha256(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _validate_sha256(value, field_name)


def _validate_aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(timezone.utc)


def _validation_field_name(info: ValidationInfo) -> str:
    """Return the concrete Pydantic field name required by shared validators."""

    if info.field_name is None:
        raise ValueError("validator field name is required")
    return info.field_name


def _canonical_sha256(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class MaterialComponentRevision(BaseModel):
    """Observed implementation identity for one material-processing component.

    Optional metadata uses a separate state field.  A missing value therefore
    cannot be mistaken for a guessed version or fingerprint.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )

    schema_version: Literal["scholar-ai-material-component-revision/v1"] = (
        "scholar-ai-material-component-revision/v1"
    )
    component_kind: MaterialComponentKind
    component_name: str = Field(min_length=1, max_length=128)
    implementation_fingerprint_state: MaterialRevisionValueState = "known"
    implementation_fingerprint: str | None
    runtime_version_state: MaterialRevisionValueState
    config_fingerprint_state: MaterialRevisionValueState
    output_fingerprint_state: MaterialRevisionValueState
    runtime_version: str | None = Field(default=None, min_length=1, max_length=128)
    config_fingerprint: str | None = None
    output_fingerprint: str | None = None

    @field_validator("component_name")
    @classmethod
    def _component_name(cls, value: str) -> str:
        if not _COMPONENT_NAME_RE.fullmatch(value):
            raise ValueError("component_name has an unsupported shape")
        return value

    @field_validator(
        "implementation_fingerprint",
        "config_fingerprint",
        "output_fingerprint",
    )
    @classmethod
    def _optional_fingerprints(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        return _validate_optional_sha256(value, _validation_field_name(info))

    @field_validator("runtime_version")
    @classmethod
    def _runtime_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _VERSION_RE.fullmatch(value):
            raise ValueError("runtime_version has an unsupported shape")
        return value

    @model_validator(mode="after")
    def _metadata_states_match_values(self) -> "MaterialComponentRevision":
        pairs = (
            (
                "implementation_fingerprint",
                self.implementation_fingerprint_state,
                self.implementation_fingerprint,
            ),
            ("runtime_version", self.runtime_version_state, self.runtime_version),
            ("config_fingerprint", self.config_fingerprint_state, self.config_fingerprint),
            ("output_fingerprint", self.output_fingerprint_state, self.output_fingerprint),
        )
        for field_name, state, value in pairs:
            if state == "known" and value is None:
                raise ValueError(f"{field_name} is required when its state is known")
            if state != "known" and value is not None:
                raise ValueError(f"{field_name} must be absent when its state is {state}")
        return self

    def fingerprint_payload(self) -> dict[str, object]:
        """Return the compatibility-safe deterministic component payload.

        The implementation state was added after the initial v1 ledger was
        introduced. Known implementations keep the original payload shape so
        an already observed v1 identity does not acquire a new fingerprint.
        Unknown or inapplicable implementations include the explicit state and
        cannot be confused with a known implementation.
        """

        payload = self.model_dump(mode="json")
        if self.implementation_fingerprint_state == "known":
            payload.pop("implementation_fingerprint_state", None)
        return cast(dict[str, object], payload)


class MaterialRevisionIdentity(BaseModel):
    """Deterministic identity for one observed material processing revision.

    ``observed_at`` is audit metadata and is intentionally excluded from the
    revision fingerprint.  Re-observing the same bytes and component identities
    therefore produces the same revision fingerprint without inventing version
    labels.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )

    schema_version: Literal["scholar-ai-material-revision-identity/v1"] = (
        "scholar-ai-material-revision-identity/v1"
    )
    project_id: str = Field(min_length=1, max_length=256)
    material_id: str = Field(min_length=1, max_length=256)
    raw_source_sha256: str
    raw_source_size_bytes: int = Field(ge=1, le=9_223_372_036_854_775_807)
    parser: MaterialComponentRevision
    extractor: MaterialComponentRevision
    ocr: MaterialComponentRevision
    chunker: MaterialComponentRevision
    extracted_text_sha256: str
    material_chunk_root_sha256: str
    observed_at: datetime
    revision_fingerprint: str = ""

    @field_validator("project_id", "material_id")
    @classmethod
    def _identifiers(cls, value: str, info: ValidationInfo) -> str:
        return _validate_identifier(value, _validation_field_name(info))

    @field_validator(
        "raw_source_sha256",
        "extracted_text_sha256",
        "material_chunk_root_sha256",
    )
    @classmethod
    def _content_fingerprints(cls, value: str, info: ValidationInfo) -> str:
        return _validate_sha256(value, _validation_field_name(info))

    @field_validator("revision_fingerprint")
    @classmethod
    def _revision_fingerprint_shape(cls, value: str) -> str:
        if not value:
            return ""
        return _validate_sha256(value, "revision_fingerprint")

    @field_validator("observed_at")
    @classmethod
    def _observed_at(cls, value: datetime) -> datetime:
        return _validate_aware_utc(value, "observed_at")

    @model_validator(mode="after")
    def _validate_components_and_fingerprint(self) -> "MaterialRevisionIdentity":
        components = (
            ("parser", self.parser),
            ("extractor", self.extractor),
            ("ocr", self.ocr),
            ("chunker", self.chunker),
        )
        for expected_kind, component in components:
            if component.component_kind != expected_kind:
                raise ValueError(
                    f"{expected_kind} must contain a {expected_kind} component revision"
                )
        computed = _canonical_sha256(self._fingerprint_payload())
        if self.revision_fingerprint and self.revision_fingerprint != computed:
            raise ValueError("revision_fingerprint does not match the deterministic identity")
        object.__setattr__(self, "revision_fingerprint", computed)
        return self

    def _fingerprint_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "material_id": self.material_id,
            "raw_source_sha256": self.raw_source_sha256,
            "raw_source_size_bytes": self.raw_source_size_bytes,
            "parser": self.parser.fingerprint_payload(),
            "extractor": self.extractor.fingerprint_payload(),
            "ocr": self.ocr.fingerprint_payload(),
            "chunker": self.chunker.fingerprint_payload(),
            "extracted_text_sha256": self.extracted_text_sha256,
            "material_chunk_root_sha256": self.material_chunk_root_sha256,
        }


class MaterialComponentSyncProgress(BaseModel):
    """Bounded progress for one caller-owned downstream component."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    component: MaterialSyncComponent
    status: MaterialSyncProgressStatus = "pending"
    outcome: MaterialSyncProgressOutcome | None = None
    operation_id: str | None = Field(default=None, min_length=1, max_length=256)
    result_fingerprint: str | None = None
    impact_count: int | None = Field(default=None, ge=0, le=1_000_000)
    applied_at: datetime | None = None

    @field_validator("operation_id")
    @classmethod
    def _operation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_identifier(value, "operation_id")

    @field_validator("result_fingerprint")
    @classmethod
    def _result_fingerprint(cls, value: str | None) -> str | None:
        return _validate_optional_sha256(value, "result_fingerprint")

    @field_validator("applied_at")
    @classmethod
    def _applied_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _validate_aware_utc(value, "applied_at")

    @model_validator(mode="after")
    def _status_matches_timestamp(self) -> "MaterialComponentSyncProgress":
        evidence = (
            self.outcome,
            self.operation_id,
            self.result_fingerprint,
            self.impact_count,
            self.applied_at,
        )
        if self.status == "pending" and any(item is not None for item in evidence):
            raise ValueError("pending component progress cannot have apply evidence")
        if self.status == "applied" and any(item is None for item in evidence):
            raise ValueError("applied component progress requires complete apply evidence")
        return self


class MaterialSyncFailureRecord(BaseModel):
    """Append-only safe failure evidence retained across retries."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    component: MaterialSyncComponent
    error_code: str = Field(min_length=1, max_length=96)
    attempt: int = Field(ge=1)
    failed_at: datetime

    @field_validator("error_code")
    @classmethod
    def _error_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not _ERROR_CODE_RE.fullmatch(normalized):
            raise ValueError("error_code has an unsupported safe-code shape")
        return normalized

    @field_validator("failed_at")
    @classmethod
    def _failed_at(cls, value: datetime) -> datetime:
        return _validate_aware_utc(value, "failed_at")


class MaterialRevisionSyncReceipt(BaseModel):
    """Durable CAS state for applying one observed material revision."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )

    schema_version: Literal["scholar-ai-material-revision-sync-receipt/v1"] = (
        "scholar-ai-material-revision-sync-receipt/v1"
    )
    receipt_id: str = Field(min_length=1, max_length=256)
    project_id: str = Field(min_length=1, max_length=256)
    material_id: str = Field(min_length=1, max_length=256)
    previous_identity: MaterialRevisionIdentity | None = None
    current_identity: MaterialRevisionIdentity
    status: MaterialSyncReceiptStatus
    required_components: tuple[MaterialSyncComponent, ...] = Field(max_length=3)
    component_progress: tuple[MaterialComponentSyncProgress, ...] = Field(max_length=3)
    version: int = Field(ge=1)
    attempts: int = Field(ge=1)
    error_code: str | None = Field(default=None, min_length=1, max_length=96)
    failed_component: MaterialSyncComponent | None = None
    failure_history: tuple[MaterialSyncFailureRecord, ...] = ()
    created_at: datetime
    updated_at: datetime
    applied_at: datetime | None = None
    failed_at: datetime | None = None

    @field_validator("receipt_id", "project_id", "material_id")
    @classmethod
    def _identifiers(cls, value: str, info: ValidationInfo) -> str:
        return _validate_identifier(value, _validation_field_name(info))

    @field_validator("required_components", mode="before")
    @classmethod
    def _required_components(
        cls,
        value: object,
    ) -> tuple[MaterialSyncComponent, ...]:
        return _normalize_components(value, allow_empty=True)

    @field_validator("component_progress", mode="before")
    @classmethod
    def _component_progress(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            raise ValueError("component_progress must be a sequence")
        if len(value) > len(MATERIAL_SYNC_COMPONENTS):
            raise ValueError("component_progress exceeds the supported components")
        return value

    @field_validator("error_code")
    @classmethod
    def _error_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not _ERROR_CODE_RE.fullmatch(normalized):
            raise ValueError("error_code has an unsupported safe-code shape")
        return normalized

    @field_validator("created_at", "updated_at", "applied_at", "failed_at")
    @classmethod
    def _timestamps(
        cls,
        value: datetime | None,
        info: ValidationInfo,
    ) -> datetime | None:
        if value is None:
            return None
        return _validate_aware_utc(value, _validation_field_name(info))

    @model_validator(mode="after")
    def _receipt_invariants(self) -> "MaterialRevisionSyncReceipt":
        identities = tuple(
            identity
            for identity in (self.previous_identity, self.current_identity)
            if identity is not None
        )
        if any(
            identity.project_id != self.project_id or identity.material_id != self.material_id
            for identity in identities
        ):
            raise ValueError("receipt identities must belong to the receipt material")
        if (
            self.previous_identity is not None
            and self.previous_identity.revision_fingerprint
            == self.current_identity.revision_fingerprint
        ):
            raise ValueError("previous_identity and current_identity must differ")

        progress_components = tuple(item.component for item in self.component_progress)
        if len(progress_components) != len(set(progress_components)):
            raise ValueError("component_progress must not contain duplicates")
        if progress_components != self.required_components:
            raise ValueError("component_progress must match required_components in order")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if any(item.attempt > self.attempts for item in self.failure_history):
            raise ValueError("failure history cannot reference a future attempt")

        if self.status == "pending":
            if self.previous_identity is None or not self.required_components:
                raise ValueError("pending receipts require a prior head and components")
            if any((self.error_code, self.failed_component, self.applied_at, self.failed_at)):
                raise ValueError("pending receipts cannot contain terminal state")
        elif self.status == "failed":
            if self.previous_identity is None or not self.required_components:
                raise ValueError("failed receipts require a prior head and components")
            if self.error_code is None or self.failed_component is None or self.failed_at is None:
                raise ValueError("failed receipts require a component, code, and timestamp")
            if self.applied_at is not None:
                raise ValueError("failed receipts cannot have applied_at")
            failed_progress = next(
                (
                    item
                    for item in self.component_progress
                    if item.component == self.failed_component
                ),
                None,
            )
            if failed_progress is None or failed_progress.status != "pending":
                raise ValueError("failed_component must identify pending component progress")
            if self.failed_at < self.created_at:
                raise ValueError("failed_at cannot precede created_at")
            if not self.failure_history or (
                self.failure_history[-1].component != self.failed_component
                or self.failure_history[-1].error_code != self.error_code
                or self.failure_history[-1].failed_at != self.failed_at
                or self.failure_history[-1].attempt != self.attempts
            ):
                raise ValueError("failed receipt must end with its current failure record")
        else:
            if self.applied_at is None:
                raise ValueError("applied receipts require applied_at")
            if any((self.error_code, self.failed_component, self.failed_at)):
                raise ValueError("applied receipts cannot contain failure state")
            if any(item.status != "applied" for item in self.component_progress):
                raise ValueError("applied receipts require all component progress")
            if self.previous_identity is None and self.required_components:
                raise ValueError("initial applied receipts do not require fanout")
            if self.previous_identity is not None and not self.required_components:
                raise ValueError("changed applied receipts require component evidence")
            if self.applied_at < self.created_at:
                raise ValueError("applied_at cannot precede created_at")
        return self


class MaterialRevisionHead(BaseModel):
    """Current fully applied material revision for one project."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    project_id: str = Field(min_length=1, max_length=256)
    material_id: str = Field(min_length=1, max_length=256)
    identity: MaterialRevisionIdentity
    applied_receipt_id: str = Field(min_length=1, max_length=256)
    applied_at: datetime

    @field_validator("project_id", "material_id", "applied_receipt_id")
    @classmethod
    def _identifiers(cls, value: str, info: ValidationInfo) -> str:
        return _validate_identifier(value, _validation_field_name(info))

    @field_validator("applied_at")
    @classmethod
    def _applied_at(cls, value: datetime) -> datetime:
        return _validate_aware_utc(value, "applied_at")

    @model_validator(mode="after")
    def _identity_matches_head(self) -> "MaterialRevisionHead":
        if (
            self.identity.project_id != self.project_id
            or self.identity.material_id != self.material_id
        ):
            raise ValueError("head identity must belong to the head material")
        return self


class MaterialRevisionStageResult(BaseModel):
    """Receipt and still-visible head returned by an atomic stage operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt: MaterialRevisionSyncReceipt
    head: MaterialRevisionHead
    replayed: bool
    observation_created: bool

    @model_validator(mode="after")
    def _head_matches_receipt_state(self) -> "MaterialRevisionStageResult":
        expected = (
            self.receipt.current_identity
            if self.receipt.status == "applied"
            else self.receipt.previous_identity
        )
        if expected is None or (
            self.head.identity.revision_fingerprint != expected.revision_fingerprint
        ):
            raise ValueError("stage result head does not match the receipt state")
        return self


class MaterialRevisionStore:
    """Project-scoped SQLite ledger for material revision synchronization.

    The caller supplies both the project id and its SQLite path.  Each public
    mutation opens a fresh connection and uses ``BEGIN IMMEDIATE``.  Revision
    observations and receipts are durable coordination records only; callers
    perform downstream work and report progress through CAS methods.
    """

    def __init__(self, db_path: str | Path, project_id: str) -> None:
        """Initialize a project-scoped material revision store.

        Args:
            db_path: Dedicated SQLite file owned by the caller's project.
            project_id: Stable project identifier accepted by all store calls.

        Raises:
            ValueError: If the project id or path is invalid.
            MaterialRevisionStoreError: If SQLite cannot initialize the schema.
        """

        if not isinstance(db_path, (str, Path)):
            raise TypeError("db_path must be a string or pathlib.Path")
        if not str(db_path).strip():
            raise ValueError("db_path must be non-empty")
        self.project_id = _validate_identifier(project_id, "project_id")
        resolved = Path(db_path).expanduser().resolve()
        if resolved.exists() and resolved.is_dir():
            raise ValueError("db_path must name a SQLite file, not a directory")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = resolved
        self._initialize_schema()

    def stage_revision(
        self,
        identity: MaterialRevisionIdentity,
        *,
        required_components: Sequence[MaterialSyncComponent] = MATERIAL_SYNC_COMPONENTS,
    ) -> MaterialRevisionStageResult:
        """Append an observation and stage its transition atomically.

        Args:
            identity: Strict current material identity for this store's project.
            required_components: Non-empty caller-owned fanout components for a
                changed revision. The first revision applies immediately and
                deliberately ignores fanout because no prior head can be stale.

        Returns:
            The durable receipt and the head visible after staging. Re-observing
            the current or active identity returns the original receipt without
            inserting another observation.

        Raises:
            ValueError: If inputs violate project or component boundaries.
            MaterialRevisionConflictError: If another revision is active or an
                identical active revision is staged with different requirements.
        """

        if not isinstance(identity, MaterialRevisionIdentity):
            raise TypeError("identity must be a MaterialRevisionIdentity")
        if identity.project_id != self.project_id:
            raise ValueError("identity project_id does not match this store")
        components = _normalize_components(required_components, allow_empty=False)

        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            canonical_identity, observation_created = self._store_observation(
                connection,
                identity,
            )
            head = self._fetch_head(connection, identity.material_id)
            if head is not None and (
                head.identity.revision_fingerprint == canonical_identity.revision_fingerprint
            ):
                receipt = self._require_receipt(
                    connection,
                    head.applied_receipt_id,
                )
                if receipt.status != "applied":
                    raise MaterialRevisionCorruptionError(
                        "current head points to a non-applied receipt"
                    )
                result = MaterialRevisionStageResult(
                    receipt=receipt,
                    head=head,
                    replayed=True,
                    observation_created=False,
                )
                connection.commit()
                return result

            active = self._fetch_active_receipt(connection, identity.material_id)
            if active is not None:
                if (
                    active.current_identity.revision_fingerprint
                    != canonical_identity.revision_fingerprint
                ):
                    raise MaterialRevisionConflictError(
                        "another material revision is pending or failed"
                    )
                if active.required_components != components:
                    raise MaterialRevisionConflictError(
                        "active revision was staged with different components"
                    )
                if head is None:
                    raise MaterialRevisionCorruptionError(
                        "active changed revision is missing its previous head"
                    )
                result = MaterialRevisionStageResult(
                    receipt=active,
                    head=head,
                    replayed=True,
                    observation_created=False,
                )
                connection.commit()
                return result

            now = _utc_now()
            receipt_id = f"mrev-{uuid4().hex}"
            if head is None:
                receipt = MaterialRevisionSyncReceipt(
                    receipt_id=receipt_id,
                    project_id=self.project_id,
                    material_id=identity.material_id,
                    previous_identity=None,
                    current_identity=canonical_identity,
                    status="applied",
                    required_components=(),
                    component_progress=(),
                    version=1,
                    attempts=1,
                    created_at=now,
                    updated_at=now,
                    applied_at=now,
                )
                self._insert_receipt(connection, receipt)
                head = MaterialRevisionHead(
                    project_id=self.project_id,
                    material_id=identity.material_id,
                    identity=canonical_identity,
                    applied_receipt_id=receipt.receipt_id,
                    applied_at=now,
                )
                self._insert_head(connection, head)
            else:
                receipt = MaterialRevisionSyncReceipt(
                    receipt_id=receipt_id,
                    project_id=self.project_id,
                    material_id=identity.material_id,
                    previous_identity=head.identity,
                    current_identity=canonical_identity,
                    status="pending",
                    required_components=components,
                    component_progress=tuple(
                        MaterialComponentSyncProgress(component=component)
                        for component in components
                    ),
                    version=1,
                    attempts=1,
                    created_at=now,
                    updated_at=now,
                )
                self._insert_receipt(connection, receipt)

            result = MaterialRevisionStageResult(
                receipt=receipt,
                head=head,
                replayed=False,
                observation_created=observation_created,
            )
            connection.commit()
            return result
        except (MaterialRevisionStoreError, TypeError, ValueError):
            connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise MaterialRevisionConflictError(
                "material revision staging violated a durable precondition"
            ) from exc
        except sqlite3.Error as exc:
            connection.rollback()
            raise MaterialRevisionStoreError("failed to stage material revision") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def mark_component_applied(
        self,
        *,
        receipt_id: str,
        component: MaterialSyncComponent,
        expected_version: int,
        outcome: MaterialSyncProgressOutcome,
        operation_id: str,
        result_fingerprint: str,
        impact_count: int,
    ) -> MaterialRevisionSyncReceipt:
        """CAS one pending downstream component to applied.

        Args:
            receipt_id: Durable receipt identifier.
            component: One of ``citation``, ``visual``, or ``reviewed``.
            expected_version: Receipt version observed by the caller.
            outcome: Whether downstream work mutated state or was a no-op.
            operation_id: Deterministic cross-store operation identifier.
            result_fingerprint: SHA-256 of the bounded downstream result.
            impact_count: Number of downstream records affected.

        Returns:
            The updated pending receipt. This method never advances the head.

        Raises:
            MaterialRevisionConflictError: If state or CAS version changed.
            MaterialRevisionNotFoundError: If the receipt is absent.
        """

        normalized_component = _normalize_component(component)
        expected = _validate_expected_version(expected_version)
        if outcome not in {"applied", "no_op"}:
            raise ValueError("outcome must be applied or no_op")
        normalized_operation_id = _validate_identifier(operation_id, "operation_id")
        normalized_result_fingerprint = _validate_sha256(
            result_fingerprint,
            "result_fingerprint",
        )
        if isinstance(impact_count, bool) or not isinstance(impact_count, int):
            raise TypeError("impact_count must be an integer")
        if impact_count < 0 or impact_count > 1_000_000:
            raise ValueError("impact_count must be between 0 and 1000000")
        if outcome == "no_op" and impact_count != 0:
            raise ValueError("no_op component outcomes require impact_count=0")
        if outcome == "applied" and impact_count < 1:
            raise ValueError("applied component outcomes require a positive impact_count")
        return self._mutate_receipt(
            receipt_id=receipt_id,
            expected_version=expected,
            mutation=lambda receipt, now: self._component_applied_receipt(
                receipt,
                component=normalized_component,
                outcome=outcome,
                operation_id=normalized_operation_id,
                result_fingerprint=normalized_result_fingerprint,
                impact_count=impact_count,
                now=now,
            ),
        )

    def fail_receipt(
        self,
        *,
        receipt_id: str,
        component: MaterialSyncComponent,
        expected_version: int,
        error_code: str,
    ) -> MaterialRevisionSyncReceipt:
        """CAS a pending receipt to failed using only a safe error code.

        Args:
            receipt_id: Durable receipt identifier.
            component: Pending downstream component that failed.
            expected_version: Receipt version observed by the caller.
            error_code: Uppercase machine code; diagnostic text is not stored.

        Returns:
            The durable failed receipt, which can later be explicitly retried.
        """

        normalized_component = _normalize_component(component)
        expected = _validate_expected_version(expected_version)
        normalized_error = str(error_code or "").strip().upper()
        if not _ERROR_CODE_RE.fullmatch(normalized_error):
            raise ValueError("error_code has an unsupported safe-code shape")
        return self._mutate_receipt(
            receipt_id=receipt_id,
            expected_version=expected,
            mutation=lambda receipt, now: self._failed_receipt(
                receipt,
                component=normalized_component,
                error_code=normalized_error,
                now=now,
            ),
        )

    def retry_receipt(
        self,
        *,
        receipt_id: str,
        expected_version: int,
    ) -> MaterialRevisionSyncReceipt:
        """CAS a failed receipt back to pending while preserving progress.

        Args:
            receipt_id: Durable failed receipt identifier.
            expected_version: Receipt version observed by the caller.

        Returns:
            A pending receipt with incremented attempt and version counters.
        """

        expected = _validate_expected_version(expected_version)
        return self._mutate_receipt(
            receipt_id=receipt_id,
            expected_version=expected,
            mutation=self._retried_receipt,
        )

    def complete_receipt(
        self,
        *,
        receipt_id: str,
        expected_version: int,
    ) -> MaterialRevisionSyncReceipt:
        """CAS a fully synchronized receipt and its material head atomically.

        Args:
            receipt_id: Pending changed-revision receipt identifier.
            expected_version: Receipt version observed by the caller.

        Returns:
            The applied receipt after the current head has moved.

        Raises:
            MaterialRevisionConflictError: If progress is incomplete, the head
                no longer matches ``previous_identity``, or CAS state changed.
        """

        normalized_receipt_id = _validate_identifier(receipt_id, "receipt_id")
        expected = _validate_expected_version(expected_version)
        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            receipt = self._require_receipt(connection, normalized_receipt_id)
            self._require_receipt_cas(receipt, expected)
            if receipt.status != "pending":
                raise MaterialRevisionConflictError("only pending receipts can complete")
            if any(item.status != "applied" for item in receipt.component_progress):
                raise MaterialRevisionConflictError(
                    "all required components must be applied before completion"
                )
            if receipt.previous_identity is None:
                raise MaterialRevisionCorruptionError(
                    "changed revision receipt is missing previous_identity"
                )

            head = self._fetch_head(connection, receipt.material_id)
            if head is None or (
                head.identity.revision_fingerprint != receipt.previous_identity.revision_fingerprint
            ):
                raise MaterialRevisionConflictError(
                    "material head no longer matches the receipt precondition"
                )
            now = _utc_now()
            updated = _replace_receipt(
                receipt,
                status="applied",
                version=receipt.version + 1,
                updated_at=now,
                applied_at=now,
            )
            self._cas_update_receipt(connection, previous=receipt, current=updated)
            cursor = connection.execute(
                """
                UPDATE material_revision_heads
                SET revision_fingerprint = ?, applied_receipt_id = ?, applied_at = ?
                WHERE project_id = ? AND material_id = ?
                  AND revision_fingerprint = ? AND applied_receipt_id = ?
                """,
                (
                    updated.current_identity.revision_fingerprint,
                    updated.receipt_id,
                    now.isoformat(),
                    self.project_id,
                    updated.material_id,
                    head.identity.revision_fingerprint,
                    head.applied_receipt_id,
                ),
            )
            if cursor.rowcount != 1:
                raise MaterialRevisionConflictError(
                    "material head changed before receipt completion"
                )
            connection.commit()
            return updated
        except (MaterialRevisionStoreError, TypeError, ValueError):
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise MaterialRevisionStoreError("failed to complete revision receipt") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_current_head(self, material_id: str) -> MaterialRevisionHead | None:
        """Return the current fully applied head for one material.

        Args:
            material_id: Stable material identifier within this store's project.

        Returns:
            The applied head, or ``None`` when no revision has been observed.
        """

        normalized_material_id = _validate_identifier(material_id, "material_id")
        connection = self._open_or_raise()
        try:
            return self._fetch_head(connection, normalized_material_id)
        except sqlite3.Error as exc:
            raise MaterialRevisionStoreError("failed to read material revision head") from exc
        finally:
            connection.close()

    def get_receipt(self, receipt_id: str) -> MaterialRevisionSyncReceipt | None:
        """Return one durable receipt.

        Args:
            receipt_id: Stable receipt identifier returned by ``stage_revision``.

        Returns:
            The validated receipt, or ``None`` when it is absent.
        """

        normalized_receipt_id = _validate_identifier(receipt_id, "receipt_id")
        connection = self._open_or_raise()
        try:
            return self._fetch_receipt(connection, normalized_receipt_id)
        except sqlite3.Error as exc:
            raise MaterialRevisionStoreError("failed to read revision receipt") from exc
        finally:
            connection.close()

    def get_active_receipt(
        self,
        material_id: str,
    ) -> MaterialRevisionSyncReceipt | None:
        """Return the pending or failed receipt used for restart recovery.

        Args:
            material_id: Stable material identifier within this store's project.

        Returns:
            The single active receipt, or ``None`` when no work needs recovery.
        """

        normalized_material_id = _validate_identifier(material_id, "material_id")
        connection = self._open_or_raise()
        try:
            return self._fetch_active_receipt(connection, normalized_material_id)
        except sqlite3.Error as exc:
            raise MaterialRevisionStoreError("failed to read active revision receipt") from exc
        finally:
            connection.close()

    def list_observations(
        self,
        material_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[MaterialRevisionIdentity, ...]:
        """List unique observed identities with bounded newest-first paging.

        Args:
            material_id: Material whose append-only identities are requested.
            limit: Page size from 1 through ``MAX_MATERIAL_REVISION_LIST_LIMIT``.
            offset: Non-negative row offset.

        Returns:
            A newest-first tuple of validated unique revision identities.
        """

        normalized_material_id = _validate_identifier(material_id, "material_id")
        bounded_limit = _validate_limit(limit)
        bounded_offset = _validate_offset(offset)
        connection = self._open_or_raise()
        try:
            rows = connection.execute(
                """
                SELECT project_id, material_id, revision_fingerprint, observed_at, raw_json
                FROM material_revision_observations
                WHERE project_id = ? AND material_id = ?
                ORDER BY observed_at DESC, revision_fingerprint DESC
                LIMIT ? OFFSET ?
                """,
                (self.project_id, normalized_material_id, bounded_limit, bounded_offset),
            ).fetchall()
            return tuple(self._load_observation_row(row) for row in rows)
        except sqlite3.Error as exc:
            raise MaterialRevisionStoreError("failed to list revision observations") from exc
        finally:
            connection.close()

    def list_receipts(
        self,
        *,
        material_id: str | None = None,
        status: MaterialSyncReceiptStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[MaterialRevisionSyncReceipt, ...]:
        """List durable receipts with bounded project-scoped paging.

        Args:
            material_id: Optional material filter.
            status: Optional pending/applied/failed filter.
            limit: Page size from 1 through ``MAX_MATERIAL_REVISION_LIST_LIMIT``.
            offset: Non-negative row offset.

        Returns:
            A newest-first tuple of validated durable receipts.
        """

        normalized_material_id = (
            _validate_identifier(material_id, "material_id") if material_id is not None else None
        )
        if status is not None and status not in {"pending", "applied", "failed"}:
            raise ValueError("status is unsupported")
        bounded_limit = _validate_limit(limit)
        bounded_offset = _validate_offset(offset)
        predicates = ["project_id = ?"]
        parameters: list[object] = [self.project_id]
        if normalized_material_id is not None:
            predicates.append("material_id = ?")
            parameters.append(normalized_material_id)
        if status is not None:
            predicates.append("status = ?")
            parameters.append(status)
        parameters.extend((bounded_limit, bounded_offset))
        query = f"""
            SELECT * FROM material_revision_sync_receipts
            WHERE {' AND '.join(predicates)}
            ORDER BY created_at DESC, receipt_id DESC
            LIMIT ? OFFSET ?
        """
        connection = self._open_or_raise()
        try:
            rows = connection.execute(query, parameters).fetchall()
            return tuple(self._load_receipt_row(row) for row in rows)
        except sqlite3.Error as exc:
            raise MaterialRevisionStoreError("failed to list revision receipts") from exc
        finally:
            connection.close()

    def _mutate_receipt(
        self,
        *,
        receipt_id: str,
        expected_version: int,
        mutation: "_ReceiptMutation",
    ) -> MaterialRevisionSyncReceipt:
        normalized_receipt_id = _validate_identifier(receipt_id, "receipt_id")
        connection = self._open_or_raise()
        try:
            connection.execute("BEGIN IMMEDIATE")
            receipt = self._require_receipt(connection, normalized_receipt_id)
            self._require_receipt_cas(receipt, expected_version)
            updated = mutation(receipt, _utc_now())
            self._cas_update_receipt(connection, previous=receipt, current=updated)
            connection.commit()
            return updated
        except (MaterialRevisionStoreError, TypeError, ValueError):
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise MaterialRevisionStoreError("failed to update revision receipt") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _component_applied_receipt(
        receipt: MaterialRevisionSyncReceipt,
        *,
        component: MaterialSyncComponent,
        outcome: MaterialSyncProgressOutcome,
        operation_id: str,
        result_fingerprint: str,
        impact_count: int,
        now: datetime,
    ) -> MaterialRevisionSyncReceipt:
        if receipt.status != "pending":
            raise MaterialRevisionConflictError("components can only update pending receipts")
        found = False
        earlier_pending = False
        progress: list[MaterialComponentSyncProgress] = []
        for item in receipt.component_progress:
            if item.component != component:
                if not found and item.status != "applied":
                    earlier_pending = True
                progress.append(item)
                continue
            found = True
            if item.status != "pending":
                raise MaterialRevisionConflictError("component is already applied")
            if earlier_pending:
                raise MaterialRevisionConflictError(
                    "components must be applied in receipt order"
                )
            progress.append(
                MaterialComponentSyncProgress(
                    component=item.component,
                    status="applied",
                    outcome=outcome,
                    operation_id=operation_id,
                    result_fingerprint=result_fingerprint,
                    impact_count=impact_count,
                    applied_at=now,
                )
            )
        if not found:
            raise MaterialRevisionConflictError("component is not required by this receipt")
        return _replace_receipt(
            receipt,
            component_progress=tuple(progress),
            version=receipt.version + 1,
            updated_at=now,
        )

    @staticmethod
    def _failed_receipt(
        receipt: MaterialRevisionSyncReceipt,
        *,
        component: MaterialSyncComponent,
        error_code: str,
        now: datetime,
    ) -> MaterialRevisionSyncReceipt:
        if receipt.status != "pending":
            raise MaterialRevisionConflictError("only pending receipts can fail")
        progress = next(
            (item for item in receipt.component_progress if item.component == component),
            None,
        )
        if progress is None or progress.status != "pending":
            raise MaterialRevisionConflictError("failed component must be pending and required")
        return _replace_receipt(
            receipt,
            status="failed",
            version=receipt.version + 1,
            updated_at=now,
            error_code=error_code,
            failed_component=component,
            failed_at=now,
            failure_history=(
                *receipt.failure_history,
                MaterialSyncFailureRecord(
                    component=component,
                    error_code=error_code,
                    attempt=receipt.attempts,
                    failed_at=now,
                ),
            ),
        )

    @staticmethod
    def _retried_receipt(
        receipt: MaterialRevisionSyncReceipt,
        now: datetime,
    ) -> MaterialRevisionSyncReceipt:
        if receipt.status != "failed":
            raise MaterialRevisionConflictError("only failed receipts can retry")
        return _replace_receipt(
            receipt,
            status="pending",
            version=receipt.version + 1,
            attempts=receipt.attempts + 1,
            updated_at=now,
            error_code=None,
            failed_component=None,
            failed_at=None,
        )

    @staticmethod
    def _require_receipt_cas(
        receipt: MaterialRevisionSyncReceipt,
        expected_version: int,
    ) -> None:
        if receipt.version != expected_version:
            raise MaterialRevisionConflictError(
                "receipt version no longer matches the caller precondition"
            )

    def _store_observation(
        self,
        connection: sqlite3.Connection,
        identity: MaterialRevisionIdentity,
    ) -> tuple[MaterialRevisionIdentity, bool]:
        row = connection.execute(
            """
            SELECT project_id, material_id, revision_fingerprint, observed_at, raw_json
            FROM material_revision_observations
            WHERE project_id = ? AND material_id = ? AND revision_fingerprint = ?
            """,
            (self.project_id, identity.material_id, identity.revision_fingerprint),
        ).fetchone()
        if row is not None:
            stored = self._load_observation_row(row)
            if stored._fingerprint_payload() != identity._fingerprint_payload():
                raise MaterialRevisionConflictError(
                    "revision fingerprint was reused for different identity data"
                )
            return stored, False
        connection.execute(
            """
            INSERT INTO material_revision_observations(
                project_id, material_id, revision_fingerprint, observed_at, raw_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                self.project_id,
                identity.material_id,
                identity.revision_fingerprint,
                identity.observed_at.isoformat(),
                identity.model_dump_json(),
            ),
        )
        return identity, True

    def _insert_receipt(
        self,
        connection: sqlite3.Connection,
        receipt: MaterialRevisionSyncReceipt,
    ) -> None:
        connection.execute(
            """
            INSERT INTO material_revision_sync_receipts(
                receipt_id, project_id, material_id,
                previous_revision_fingerprint, current_revision_fingerprint,
                status, version, attempts, error_code, created_at, updated_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt.receipt_id,
                receipt.project_id,
                receipt.material_id,
                (
                    receipt.previous_identity.revision_fingerprint
                    if receipt.previous_identity is not None
                    else None
                ),
                receipt.current_identity.revision_fingerprint,
                receipt.status,
                receipt.version,
                receipt.attempts,
                receipt.error_code,
                receipt.created_at.isoformat(),
                receipt.updated_at.isoformat(),
                receipt.model_dump_json(),
            ),
        )

    def _insert_head(
        self,
        connection: sqlite3.Connection,
        head: MaterialRevisionHead,
    ) -> None:
        connection.execute(
            """
            INSERT INTO material_revision_heads(
                project_id, material_id, revision_fingerprint,
                applied_receipt_id, applied_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                head.project_id,
                head.material_id,
                head.identity.revision_fingerprint,
                head.applied_receipt_id,
                head.applied_at.isoformat(),
            ),
        )

    def _cas_update_receipt(
        self,
        connection: sqlite3.Connection,
        *,
        previous: MaterialRevisionSyncReceipt,
        current: MaterialRevisionSyncReceipt,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE material_revision_sync_receipts
            SET status = ?, version = ?, attempts = ?, error_code = ?,
                updated_at = ?, raw_json = ?
            WHERE receipt_id = ? AND project_id = ?
              AND version = ? AND status = ?
            """,
            (
                current.status,
                current.version,
                current.attempts,
                current.error_code,
                current.updated_at.isoformat(),
                current.model_dump_json(),
                previous.receipt_id,
                self.project_id,
                previous.version,
                previous.status,
            ),
        )
        if cursor.rowcount != 1:
            raise MaterialRevisionConflictError(
                "receipt changed before the CAS update could commit"
            )

    def _fetch_head(
        self,
        connection: sqlite3.Connection,
        material_id: str,
    ) -> MaterialRevisionHead | None:
        row = connection.execute(
            """
            SELECT h.project_id, h.material_id, h.revision_fingerprint,
                   h.applied_receipt_id, h.applied_at,
                   o.observed_at, o.raw_json
            FROM material_revision_heads AS h
            JOIN material_revision_observations AS o
              ON o.project_id = h.project_id
             AND o.material_id = h.material_id
             AND o.revision_fingerprint = h.revision_fingerprint
            WHERE h.project_id = ? AND h.material_id = ?
            """,
            (self.project_id, material_id),
        ).fetchone()
        if row is None:
            return None
        identity = self._load_identity(row["raw_json"], "head observation")
        if (
            row["project_id"] != identity.project_id
            or row["material_id"] != identity.material_id
            or row["revision_fingerprint"] != identity.revision_fingerprint
            or row["observed_at"] != identity.observed_at.isoformat()
        ):
            raise MaterialRevisionCorruptionError(
                "material revision head does not match its observation"
            )
        receipt = self._fetch_receipt(connection, row["applied_receipt_id"])
        if receipt is None:
            raise MaterialRevisionCorruptionError(
                "material revision head receipt is missing"
            )
        if (
            receipt.status != "applied"
            or receipt.receipt_id != row["applied_receipt_id"]
            or receipt.project_id != row["project_id"]
            or receipt.material_id != row["material_id"]
            or receipt.current_identity.revision_fingerprint
            != row["revision_fingerprint"]
            or receipt.applied_at is None
            or receipt.applied_at.isoformat() != row["applied_at"]
        ):
            raise MaterialRevisionCorruptionError(
                "material revision head receipt does not match its applied receipt"
            )
        try:
            return MaterialRevisionHead(
                project_id=row["project_id"],
                material_id=row["material_id"],
                identity=identity,
                applied_receipt_id=row["applied_receipt_id"],
                applied_at=row["applied_at"],
            )
        except (TypeError, ValidationError, ValueError) as exc:
            raise MaterialRevisionCorruptionError(
                "persisted material revision head is invalid"
            ) from exc

    def _fetch_receipt(
        self,
        connection: sqlite3.Connection,
        receipt_id: str,
    ) -> MaterialRevisionSyncReceipt | None:
        row = connection.execute(
            """
            SELECT * FROM material_revision_sync_receipts
            WHERE project_id = ? AND receipt_id = ?
            """,
            (self.project_id, receipt_id),
        ).fetchone()
        return self._load_receipt_row(row) if row is not None else None

    def _require_receipt(
        self,
        connection: sqlite3.Connection,
        receipt_id: str,
    ) -> MaterialRevisionSyncReceipt:
        receipt = self._fetch_receipt(connection, receipt_id)
        if receipt is None:
            raise MaterialRevisionNotFoundError("material revision receipt was not found")
        return receipt

    def _fetch_active_receipt(
        self,
        connection: sqlite3.Connection,
        material_id: str,
    ) -> MaterialRevisionSyncReceipt | None:
        rows = connection.execute(
            """
            SELECT * FROM material_revision_sync_receipts
            WHERE project_id = ? AND material_id = ?
              AND status IN ('pending', 'failed')
            ORDER BY created_at DESC, receipt_id DESC
            LIMIT 2
            """,
            (self.project_id, material_id),
        ).fetchall()
        if len(rows) > 1:
            raise MaterialRevisionCorruptionError(
                "material has more than one active revision receipt"
            )
        return self._load_receipt_row(rows[0]) if rows else None

    def _load_observation_row(self, row: sqlite3.Row) -> MaterialRevisionIdentity:
        identity = self._load_identity(row["raw_json"], "revision observation")
        if (
            row["project_id"] != identity.project_id
            or row["material_id"] != identity.material_id
            or row["revision_fingerprint"] != identity.revision_fingerprint
            or row["observed_at"] != identity.observed_at.isoformat()
            or identity.project_id != self.project_id
        ):
            raise MaterialRevisionCorruptionError(
                "revision observation columns do not match its payload"
            )
        return identity

    def _load_receipt_row(self, row: sqlite3.Row) -> MaterialRevisionSyncReceipt:
        try:
            receipt = MaterialRevisionSyncReceipt.model_validate_json(row["raw_json"])
        except (TypeError, ValidationError, ValueError) as exc:
            raise MaterialRevisionCorruptionError(
                "persisted material revision receipt is invalid"
            ) from exc
        previous_fingerprint = (
            receipt.previous_identity.revision_fingerprint
            if receipt.previous_identity is not None
            else None
        )
        if (
            row["receipt_id"] != receipt.receipt_id
            or row["project_id"] != receipt.project_id
            or row["material_id"] != receipt.material_id
            or row["previous_revision_fingerprint"] != previous_fingerprint
            or row["current_revision_fingerprint"] != receipt.current_identity.revision_fingerprint
            or row["status"] != receipt.status
            or row["version"] != receipt.version
            or row["attempts"] != receipt.attempts
            or row["error_code"] != receipt.error_code
            or row["created_at"] != receipt.created_at.isoformat()
            or row["updated_at"] != receipt.updated_at.isoformat()
            or receipt.project_id != self.project_id
        ):
            raise MaterialRevisionCorruptionError(
                "revision receipt columns do not match its payload"
            )
        return receipt

    @staticmethod
    def _load_identity(raw_json: str, label: str) -> MaterialRevisionIdentity:
        try:
            return MaterialRevisionIdentity.model_validate_json(raw_json)
        except (TypeError, ValidationError, ValueError) as exc:
            raise MaterialRevisionCorruptionError(f"persisted {label} is invalid") from exc

    def _open(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.db_path),
            timeout=5.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _open_or_raise(self) -> sqlite3.Connection:
        try:
            return self._open()
        except sqlite3.Error as exc:
            raise MaterialRevisionStoreError("unable to open material revision store") from exc

    def _initialize_schema(self) -> None:
        connection = self._open_or_raise()
        try:
            current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current_version not in {0, MATERIAL_REVISION_STORE_SCHEMA_VERSION}:
                raise MaterialRevisionStoreError(
                    "material revision store schema version is unsupported"
                )
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS material_revision_observations (
                    project_id TEXT NOT NULL,
                    material_id TEXT NOT NULL,
                    revision_fingerprint TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    PRIMARY KEY(project_id, material_id, revision_fingerprint)
                )
                """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS material_revision_sync_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    material_id TEXT NOT NULL,
                    previous_revision_fingerprint TEXT,
                    current_revision_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'applied', 'failed')),
                    version INTEGER NOT NULL CHECK(version >= 1),
                    attempts INTEGER NOT NULL CHECK(attempts >= 1),
                    error_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    FOREIGN KEY(project_id, material_id, current_revision_fingerprint)
                        REFERENCES material_revision_observations(
                            project_id, material_id, revision_fingerprint
                        ) ON DELETE RESTRICT,
                    FOREIGN KEY(project_id, material_id, previous_revision_fingerprint)
                        REFERENCES material_revision_observations(
                            project_id, material_id, revision_fingerprint
                        ) ON DELETE RESTRICT
                )
                """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS material_revision_heads (
                    project_id TEXT NOT NULL,
                    material_id TEXT NOT NULL,
                    revision_fingerprint TEXT NOT NULL,
                    applied_receipt_id TEXT NOT NULL,
                    applied_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, material_id),
                    FOREIGN KEY(project_id, material_id, revision_fingerprint)
                        REFERENCES material_revision_observations(
                            project_id, material_id, revision_fingerprint
                        ) ON DELETE RESTRICT,
                    FOREIGN KEY(applied_receipt_id)
                        REFERENCES material_revision_sync_receipts(receipt_id)
                        ON DELETE RESTRICT
                )
                """)
            connection.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS ux_material_revision_active_receipt
                ON material_revision_sync_receipts(project_id, material_id)
                WHERE status IN ('pending', 'failed')
                """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_material_revision_observations_time
                ON material_revision_observations(project_id, material_id, observed_at)
                """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_material_revision_receipts_status
                ON material_revision_sync_receipts(
                    project_id, status, updated_at, receipt_id
                )
                """)
            connection.execute(f"PRAGMA user_version = {MATERIAL_REVISION_STORE_SCHEMA_VERSION}")
            connection.commit()
        except MaterialRevisionStoreError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise MaterialRevisionStoreError(
                "failed to initialize material revision store"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


_ReceiptMutation = Callable[
    [MaterialRevisionSyncReceipt, datetime],
    MaterialRevisionSyncReceipt,
]


def _normalize_component(component: object) -> MaterialSyncComponent:
    if not isinstance(component, str) or component not in MATERIAL_SYNC_COMPONENTS:
        raise ValueError("component must be citation, visual, or reviewed")
    return cast(MaterialSyncComponent, component)


def _normalize_components(
    value: object,
    *,
    allow_empty: bool,
) -> tuple[MaterialSyncComponent, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("required_components must be a sequence")
    normalized = tuple(_normalize_component(component) for component in value)
    if len(normalized) != len(set(normalized)):
        raise ValueError("required_components must not contain duplicates")
    if not normalized and not allow_empty:
        raise ValueError("required_components must not be empty")
    if len(normalized) > len(MATERIAL_SYNC_COMPONENTS):
        raise ValueError("required_components exceeds supported components")
    selected = set(normalized)
    return tuple(component for component in MATERIAL_SYNC_COMPONENTS if component in selected)


def _validate_expected_version(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("expected_version must be a positive integer")
    return value


def _validate_limit(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_MATERIAL_REVISION_LIST_LIMIT
    ):
        raise ValueError(f"limit must be between 1 and {MAX_MATERIAL_REVISION_LIST_LIMIT}")
    return value


def _validate_offset(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("offset must be a non-negative integer")
    return value


def _replace_receipt(
    receipt: MaterialRevisionSyncReceipt,
    **updates: object,
) -> MaterialRevisionSyncReceipt:
    payload = receipt.model_dump(mode="python")
    payload.update(updates)
    return MaterialRevisionSyncReceipt.model_validate(payload)


__all__ = [
    "MATERIAL_REVISION_STORE_SCHEMA_VERSION",
    "MATERIAL_SYNC_COMPONENTS",
    "MAX_MATERIAL_REVISION_LIST_LIMIT",
    "MaterialComponentKind",
    "MaterialComponentRevision",
    "MaterialComponentSyncProgress",
    "MaterialRevisionConflictError",
    "MaterialRevisionCorruptionError",
    "MaterialRevisionHead",
    "MaterialRevisionIdentity",
    "MaterialRevisionNotFoundError",
    "MaterialRevisionStageResult",
    "MaterialRevisionStore",
    "MaterialRevisionStoreError",
    "MaterialRevisionSyncReceipt",
    "MaterialRevisionValueState",
    "MaterialSyncComponent",
    "MaterialSyncFailureRecord",
    "MaterialSyncProgressOutcome",
    "MaterialSyncProgressStatus",
    "MaterialSyncReceiptStatus",
]
