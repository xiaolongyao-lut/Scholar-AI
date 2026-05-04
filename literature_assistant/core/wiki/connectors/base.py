from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, Sequence


ConnectorNamespace = Literal["obsidian", "pdf", "zotero", "endnote"]


class ConnectorPermissionError(PermissionError):
    """Raised when a connector tries to read outside explicitly allowed roots."""


@dataclass(frozen=True)
class ConnectorSource:
    """Read-only source descriptor returned by connector scans.

    Path is retained for local follow-up reads, while public reports should use
    ``metadata["relative_path"]`` or sanitized messages to avoid leaking roots.
    """

    source_id: str
    source_type: str
    title: str
    path: Path
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ConnectorScanReport:
    """Dry-run connector scan result.

    ``would_write`` is deliberately false for Wave 13 connectors; callers must
    introduce a separate import/index step before persistence is allowed.
    """

    connector: str
    root: str
    source_count: int
    source_ids: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    would_write: bool = False


@dataclass(frozen=True)
class ConnectorFieldSpec:
    """Machine-readable external connector field contract.

    ``field_name`` is stable and source-specific; ``privacy`` describes whether
    the value can contain a local path, user note, or bibliographic metadata.
    """

    field_name: str
    value_shape: str
    required: bool = False
    privacy: str = "bibliographic_metadata"


@dataclass(frozen=True)
class ConnectorSpec:
    """Spec-only connector contract for external literature managers.

    The spec does not open databases or vaults; it documents readable fields and
    filesystem boundaries for future connector implementations.
    """

    namespace: ConnectorNamespace
    display_name: str
    root_hint: str
    readable_fields: tuple[ConnectorFieldSpec, ...]
    supports_content_read: bool
    read_only: bool = True
    writes_user_library: bool = False


class ReadOnlyConnector(Protocol):
    """Minimal read-only connector interface for Wave 13."""

    def list_sources(self) -> list[ConnectorSource]: ...

    def read_source(self, source_id: str) -> str: ...

    def extract_metadata(self, source_id: str) -> dict[str, object]: ...

    def dry_run_scan(self) -> ConnectorScanReport: ...


def ensure_path_within_allowed_roots(path: Path, allowed_roots: Sequence[Path]) -> Path:
    """Resolve ``path`` only when it stays inside an explicit configured root.

    Raises:
        ConnectorPermissionError: If no roots are configured or the resolved
            path is outside every allowed root.
    """

    if not allowed_roots:
        raise ConnectorPermissionError("External connector path requires a configured root.")

    candidate = Path(path).resolve()
    for root in allowed_roots:
        resolved_root = Path(root).resolve()
        if candidate == resolved_root or resolved_root in candidate.parents:
            return candidate

    raise ConnectorPermissionError("Connector path is outside configured connector roots.")


def connector_slug(value: str) -> str:
    """Return a deterministic path-safe slug for connector-local identifiers."""

    if not isinstance(value, str):
        raise TypeError("value must be a string")
    text = value.strip().lower()
    chars: list[str] = []
    for char in text:
        if char.isalnum():
            chars.append(char)
        elif char in {" ", "-", "_", ".", "/", "\\"}:
            chars.append("-")
    slug = "-".join(part for part in "".join(chars).split("-") if part)
    if slug:
        return slug[:96]
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def format_connector_source_id(namespace: str, local_id: str) -> str:
    """Format a namespaced connector source ID.

    Args:
        namespace: Simple connector namespace such as ``obsidian`` or ``zotero``.
        local_id: Connector-local stable identifier, usually a relative path or
            manager item key.
    """

    normalized_namespace = namespace.strip().lower()
    if not normalized_namespace or any(char in normalized_namespace for char in ":/\\"):
        raise ValueError("connector namespace must be a simple non-empty token")
    if not local_id.strip():
        raise ValueError("local_id cannot be empty")
    return f"{normalized_namespace}:{connector_slug(local_id)}"


def path_to_safe_relative_string(path: Path, root: Path) -> str:
    """Return a POSIX relative path after resolving both path and root."""

    resolved_root = Path(root).resolve()
    resolved_path = Path(path).resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ConnectorPermissionError("Connector path is outside configured connector roots.") from exc


def unique_connector_source_id(namespace: str, local_id: str, seen_source_ids: set[str]) -> str:
    """Return a deterministic source ID, adding a short hash only on collisions."""

    source_id = format_connector_source_id(namespace, local_id)
    if source_id not in seen_source_ids:
        seen_source_ids.add(source_id)
        return source_id

    digest = hashlib.sha256(local_id.encode("utf-8")).hexdigest()[:8]
    source_id_with_digest = f"{source_id}-{digest}"
    seen_source_ids.add(source_id_with_digest)
    return source_id_with_digest


def sanitize_connector_error(error: BaseException) -> str:
    """Return a public-safe connector error message without local paths."""

    error_type = type(error).__name__
    if isinstance(error, ConnectorPermissionError):
        return f"{error_type}: {error}"
    if isinstance(error, (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError)):
        return f"{error_type}: connector source could not be read"
    return f"{error_type}: connector operation failed"
