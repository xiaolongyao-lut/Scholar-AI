"""MCP local installer models (S2 / plan 2026-05-20 §A2).

Separate from ``models/mcp.py`` to keep the registry / runtime config models
focused. These models describe the install-time contract:

- ``McpPackageScanRequest`` / ``McpPackageScanResult`` — scanner I/O
- ``McpLaunchCandidate`` — one detected way to start the server, identified
  by a content sha (Locked Revisions M5: install requests reference candidates
  by sha, never by list index, to survive scan_id refresh / re-order)
- ``McpInstallConfigField`` — generated non-secret UI field
- ``McpRequiredCredential`` — credential ref slot to bind via CredentialPicker
- ``McpScanWarning`` — observation about the package, not a hard error
- ``McpInstallPlan`` — what would be created on confirm; preview/install share it

None of these carry secrets or persist anything; secrets enter the runtime
only when the installer writes a McpServerConfig with env_refs.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


SCAN_ID_TTL_SECONDS = 300  # 5 min (plan M5)
"""Scan_id lifetime. Beyond this the installer rejects with ``scan_expired``.
Short TTL prevents stale rescans from racing the real package state on disk."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class McpScanConfidence(str, Enum):
    """How sure the scanner is that its launch_candidate will actually work."""

    HIGH = "high"
    """First-class signal: literature-mcp.json / lit-mcp.json / mcp.json /
    server.json present and well-formed."""

    MEDIUM = "medium"
    """Reliable secondary signal: package.json scripts/bin or pyproject.toml
    project.scripts entry-point declared."""

    LOW = "low"
    """Heuristic only: README command examples / requirements.txt presence.
    Wizard should require the user to confirm the candidate explicitly."""

    NONE = "none"
    """No safe candidate; ``needs_manual_launch=True`` and the wizard routes
    the user to the Advanced / manual form."""


class McpScanWarningLevel(str, Enum):
    INFO = "info"
    """Observation; install can proceed without acknowledgement."""

    WARN = "warn"
    """Notable but non-blocking; UI should surface but allow proceeding."""

    BLOCK = "block"
    """Install must not proceed until the user resolves it (e.g. unsafe path,
    shell metacharacter in detected command)."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def compute_launch_candidate_sha(command: str, args: list[str], cwd: str) -> str:
    """Stable content-addressed id for a launch candidate (plan M5).

    Used so install requests can reference a candidate by sha rather than
    list index — re-scan can re-order candidates without breaking pending
    install confirmations.

    The hash is intentionally NUL-separated to avoid argv-glue collisions
    ("a b" vs ["a","b"] hash differently).
    """
    args_glue = "\x01".join(args)
    material = "\x00".join([command, args_glue, cwd]).encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16]


def generate_scan_id() -> str:
    return f"scan_{uuid.uuid4().hex[:16]}"


def compute_scan_expiry(now: datetime | None = None) -> str:
    base = now or _utc_now()
    return _utc_iso(base + timedelta(seconds=SCAN_ID_TTL_SECONDS))


# ---------------------------------------------------------------------------
# Warning / candidate sub-models
# ---------------------------------------------------------------------------


class McpScanWarning(BaseModel):
    """One observation produced by the scanner.

    Codes are stable identifiers so the frontend / tests can switch on them.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    level: McpScanWarningLevel
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=512)
    field: str | None = Field(default=None, max_length=128)
    """Optional pointer to the offending field for UI inline display."""


class McpLaunchCandidate(BaseModel):
    """One detected stdio launch invocation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    command: str = Field(min_length=1, max_length=512)
    args: list[str] = Field(default_factory=list, max_length=64)
    cwd: str = Field(default=".", max_length=256)
    """Relative to the scanned source_path (normalized at install time)."""
    confidence: McpScanConfidence
    source: str = Field(min_length=1, max_length=128)
    """Where the scanner saw this candidate, e.g. ``literature-mcp.json`` or
    ``package.json:scripts.start``. Stable string for audit."""
    sha: str = Field(min_length=16, max_length=64)


# ---------------------------------------------------------------------------
# Generated UI fields
# ---------------------------------------------------------------------------


class _ConfigFieldBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    env: str = Field(min_length=1, max_length=128)
    required: bool = True
    description: str = Field(default="", max_length=512)


# v1 type allowlist; M-type extensions stay in v2.
CONFIG_FIELD_TYPES = frozenset({"text", "select"})


class McpInstallConfigField(_ConfigFieldBase):
    """Non-secret config field generated for the install wizard.

    Examples: ``VISION_PROVIDER`` (select with options), ``DEFAULT_TIMEOUT``
    (text). For secrets use ``McpRequiredCredential`` instead — those get
    bound through the CredentialPicker and stored as env_refs.
    """

    type: str = Field(min_length=1, max_length=32)
    default: str | None = Field(default=None, max_length=256)
    options: list[dict[str, str]] | None = None
    """For ``type=select``: list of ``{"value": "...", "label": "..."}``."""

    def __init__(self, **data):
        super().__init__(**data)
        if self.type not in CONFIG_FIELD_TYPES:
            raise ValueError(
                f"config field type {self.type!r} not in v1 allowlist "
                f"{sorted(CONFIG_FIELD_TYPES)}"
            )


# v1 credential kind allowlist.
CREDENTIAL_KINDS = frozenset({"api_key"})


class McpRequiredCredential(_ConfigFieldBase):
    """A credential reference slot that the install wizard binds via the
    CredentialPicker. After install, the installer writes
    ``McpStdioConfig.env_refs[env] = credential_id``.
    """

    kind: str = Field(default="api_key", max_length=32)
    provider_hints: list[str] = Field(default_factory=list, max_length=16)
    """Suggested ``RuntimeCredential.provider`` values for highlighting in
    the picker. Strings only — must align with the credentials center
    provider field by convention (no enum coupling in v1)."""

    def __init__(self, **data):
        super().__init__(**data)
        if self.kind not in CREDENTIAL_KINDS:
            raise ValueError(
                f"credential kind {self.kind!r} not in v1 allowlist "
                f"{sorted(CREDENTIAL_KINDS)}"
            )


# ---------------------------------------------------------------------------
# Scan request / result
# ---------------------------------------------------------------------------


class McpPackageScanRequest(BaseModel):
    """Body of ``POST /api/mcp/installations/scan``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_path: str = Field(min_length=1, max_length=1024)
    """Local filesystem path: directory, executable, or zip. Remote URLs
    are rejected by the scanner (plan §Non-goals)."""
    template_hint: str | None = Field(default=None, max_length=64)
    """Optional hint from a Recommended-view card to bias scanner heuristics
    (e.g. ``vision-auxiliary``). The scanner uses this only as a tiebreaker;
    decisions still come from on-disk evidence."""


class McpPackageScanResult(BaseModel):
    """Response of ``POST /api/mcp/installations/scan``.

    Either yields a viable install plan (``confidence != NONE``,
    ``launch_candidates`` non-empty) OR signals ``needs_manual_launch`` so
    the wizard routes the user to the Advanced manual form.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scan_id: str
    source_path: str
    """Normalized absolute path. May differ from request if scanner walked
    into a subdirectory (e.g. archive root)."""
    package_id: str = Field(default="", max_length=128)
    display_name: str = Field(default="", max_length=128)
    description: str = Field(default="", max_length=1024)
    version: str = Field(default="", max_length=64)
    confidence: McpScanConfidence
    transport: str = Field(default="stdio", max_length=32)
    """Currently always ``stdio``; ``streamable_http`` packages require a
    manifest with ``transport=streamable_http`` (handled by installer, not
    scanner heuristics)."""
    launch_candidates: list[McpLaunchCandidate] = Field(default_factory=list)
    config_fields: list[McpInstallConfigField] = Field(default_factory=list)
    required_credentials: list[McpRequiredCredential] = Field(default_factory=list)
    expected_tools: list[str] = Field(default_factory=list, max_length=64)
    capabilities: list[str] = Field(default_factory=list, max_length=16)
    warnings: list[McpScanWarning] = Field(default_factory=list)
    needs_manual_launch: bool = False
    expires_at: str
    """ISO-8601 UTC scan_id expiry (plan M5)."""


__all__ = [
    "CONFIG_FIELD_TYPES",
    "CREDENTIAL_KINDS",
    "McpInstallConfigField",
    "McpLaunchCandidate",
    "McpPackageScanRequest",
    "McpPackageScanResult",
    "McpRequiredCredential",
    "McpScanConfidence",
    "McpScanWarning",
    "McpScanWarningLevel",
    "SCAN_ID_TTL_SECONDS",
    "compute_launch_candidate_sha",
    "compute_scan_expiry",
    "generate_scan_id",
]
