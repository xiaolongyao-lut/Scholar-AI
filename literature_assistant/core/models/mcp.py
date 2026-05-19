"""MCP server config + tool descriptor models (Phase 1A / TASK-101).

Two-field trust model per plan v0.3 §4.3:
  - provenance: where the server config came from (LLM-credentials enum)
  - approval_state: where it sits in the local approval lifecycle
                    (registered -> catalog_reviewed -> enabled_for_session)

Tool capability tags per plan v0.3 §4.5: read / write / network / filesystem
/ destructive / unknown. unknown defaults to approval-required.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MCP_SERVER_FINGERPRINT_VERSION = "v2"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class McpTransport(str, Enum):
    """Wire transport for an MCP server."""

    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


class McpProvenance(str, Enum):
    """Where the server config originated. Mirrors credentials.CredentialTrustSource
    vocabulary so audit / UI patterns stay aligned across the two registries.
    """

    OFFICIAL_PROVIDER = "official_provider"
    RUNTIME_USER_CONFIRMED = "runtime_user_confirmed"
    RUNTIME_UNTRUSTED_CUSTOM = "runtime_untrusted_custom"


class McpApprovalState(str, Enum):
    """Approval lifecycle. Forward-only; downgrade requires explicit reset
    back to ``registered`` (Phase 1B will enforce the state machine).
    """

    REGISTERED = "registered"
    CATALOG_REVIEWED = "catalog_reviewed"
    ENABLED_FOR_SESSION = "enabled_for_session"


class McpToolCapability(str, Enum):
    """Capability tag attached to each tool descriptor for elevation gating."""

    READ = "read"
    WRITE = "write"
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    DESTRUCTIVE = "destructive"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def mask_env_value(value: str) -> str:
    """Mask an env value for public dump. Mirrors mask_api_key shape."""
    if not value:
        return ""
    s = value.strip()
    if len(s) <= 8:
        return "***"
    return f"{s[:4]}...{s[-4:]}"


# ---------------------------------------------------------------------------
# Sub-models: stdio + streamable_http transports
# ---------------------------------------------------------------------------


class McpStdioConfig(BaseModel):
    """Argv-only launch config for stdio MCP servers (Q3a-hardened: no shell)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    command: str = Field(min_length=1, max_length=512)
    args: list[str] = Field(default_factory=list, max_length=64)
    env: dict[str, str] = Field(default_factory=dict)
    """Server-specific env vars (e.g. SERPAPI_KEY). Public dumps mask values.

    Prefer ``env_refs`` for secrets — values here are stored in plaintext
    on disk and must be masked in public responses. Suitable for non-secret
    config like ``DEBUG=1`` or ``LOG_LEVEL=info``.
    """
    env_refs: dict[str, str] = Field(default_factory=dict)
    """Env var name -> RuntimeCredential ``credential_id`` reference
    (plan 2026-05-20 §Locked Revisions M3, single-source-of-truth model).

    Resolved at process spawn by
    ``mcp_runtime.credential_env_resolver`` and merged with ``env`` before
    ``prepare_subprocess_env``. Refs themselves are non-sensitive
    (``credential_id`` is an opaque UUID); public dumps return them verbatim.
    """
    cwd_relative: str | None = Field(default=None, max_length=128)
    """Optional sub-path inside the per-server sandbox cwd. None = sandbox root."""

    @field_validator("command")
    @classmethod
    def _no_shell_metachars(cls, v: str) -> str:
        # Phase 1A: reject obvious shell metacharacters in the command itself.
        # Full command-risk lint lives in Phase 1B security_policy.
        forbidden = set("|;&`$<>()\n\r")
        if any(ch in v for ch in forbidden):
            raise ValueError(
                f"command must not contain shell metacharacters: {sorted(ch for ch in v if ch in forbidden)}"
            )
        return v


class McpStreamableHttpConfig(BaseModel):
    """HTTP transport config. Persisted from day 1; execution is feature-flagged
    off until later slice (plan v0.3 §4.4).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: str = Field(min_length=1, max_length=512)
    headers: dict[str, str] = Field(default_factory=dict)
    """Auth/custom headers. Values masked in public dump.

    Prefer ``header_refs`` for ``Authorization``/``X-API-Key``-style secrets
    so raw values never touch disk in the MCP store.
    """
    header_refs: dict[str, str] = Field(default_factory=dict)
    """Header name -> RuntimeCredential ``credential_id`` reference
    (plan 2026-05-20 §Locked Revisions M3, single-source-of-truth model).

    Resolved at HTTP request build time and merged with ``headers``
    before the request leaves the client.
    """
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)


# ---------------------------------------------------------------------------
# Tool descriptor (cached output of list_tools())
# ---------------------------------------------------------------------------


class McpToolDescriptor(BaseModel):
    """One MCP tool advertised by a server. Cached in the catalog with a
    fingerprint so we can detect catalog drift on refresh.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    """Server-local tool name (without the ``mcp__{slug}__`` namespace prefix)."""
    description: str = Field(default="", max_length=4096)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    capability: McpToolCapability = McpToolCapability.UNKNOWN


# ---------------------------------------------------------------------------
# Pending-call protocol (Phase 3 / TASK-301)
# ---------------------------------------------------------------------------


class PendingMcpToolCall(BaseModel):
    """A tool call awaiting operator approval (modal-driven UX).

    Created by the runner when ``classify_action(capability) == "ask"``.
    Lives in the in-memory ``PendingCallStore`` until the operator
    approves / rejects via ``POST /api/mcp/pending-calls/{id}/decide``
    or it times out (``PENDING_CALL_TIMEOUT_SECONDS_DEFAULT=60``).

    Fields are deliberately minimal: no raw arguments (use
    ``args_preview`` which the caller is responsible for redacting);
    the frontend already trusts the upstream redaction per D-MCPUX-3 +
    `McpToolApprovalModal.tsx` §1.4.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    """uuid hex (32 chars) by default; never carries PII."""
    server_id: str = Field(min_length=1, max_length=128)
    tool_name: str = Field(min_length=1, max_length=256)
    """Server-local tool name (without the ``mcp__{slug}__`` prefix)."""
    capability: McpToolCapability
    """Backend classification — server-supplied annotation is advisory
    only per D-MCPUX-2."""
    args_preview: str = Field(default="", max_length=4096)
    """Caller-redacted preview of arguments. Modal renders verbatim."""
    created_at: str
    """ISO-8601 UTC timestamp."""


# ---------------------------------------------------------------------------
# Public-facing API: Create / Update / Public / internal
# ---------------------------------------------------------------------------


class _McpServerBaseFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=128)
    server_slug: str = Field(min_length=1, max_length=64)
    """URL-safe slug used as the prefix in ``mcp__{server_slug}__{tool}``
    namespace. Validated via _SLUG_RE."""
    transport: McpTransport
    stdio: McpStdioConfig | None = None
    http: McpStreamableHttpConfig | None = None
    provenance: McpProvenance = McpProvenance.RUNTIME_UNTRUSTED_CUSTOM
    tags: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=1024)

    @field_validator("server_slug")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(
                "server_slug must match [a-z0-9][a-z0-9_-]{0,63} "
                "(lowercase, alphanumeric, hyphen/underscore allowed)"
            )
        return v

    @model_validator(mode="after")
    def _validate_transport_block_present(self) -> "_McpServerBaseFields":
        if self.transport == McpTransport.STDIO:
            if self.stdio is None:
                raise ValueError("transport=stdio requires `stdio` block")
            if self.http is not None:
                raise ValueError("transport=stdio must not set `http` block")
        elif self.transport == McpTransport.STREAMABLE_HTTP:
            if self.http is None:
                raise ValueError("transport=streamable_http requires `http` block")
            if self.stdio is not None:
                raise ValueError(
                    "transport=streamable_http must not set `stdio` block"
                )
        return self


class McpServerConfigCreate(_McpServerBaseFields):
    """Body of POST /api/mcp/servers. New servers always start at
    ``approval_state=registered`` regardless of the requested provenance —
    callers cannot self-elevate at register time (Q2b).
    """


class McpServerConfigUpdate(BaseModel):
    """Body of PUT /api/mcp/servers/{id}. All fields optional; identity
    fields (server_slug, transport) cannot change after create.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=128)
    stdio: McpStdioConfig | None = None
    http: McpStreamableHttpConfig | None = None
    provenance: McpProvenance | None = None
    tags: list[str] | None = None
    notes: str | None = Field(default=None, max_length=1024)
    approval_state: McpApprovalState | None = None
    """Forward-only transitions enforced at the store layer."""


class McpServerConfig(_McpServerBaseFields):
    """Full domain model. Persisted in the runtime store; never serialized
    to public API responses (use ``McpServerConfigPublic`` instead) because
    ``stdio.env`` and ``http.headers`` carry secrets in plaintext.
    """

    server_id: str
    approval_state: McpApprovalState = McpApprovalState.REGISTERED
    fingerprint: str
    fingerprint_version: str = MCP_SERVER_FINGERPRINT_VERSION
    created_at: str
    updated_at: str

    @classmethod
    def from_create(cls, body: McpServerConfigCreate) -> "McpServerConfig":
        ts = _utc_now_iso()
        sid = f"mcp_{uuid.uuid4().hex[:16]}"
        fingerprint = _compute_server_fingerprint(body)
        return cls(
            server_id=sid,
            approval_state=McpApprovalState.REGISTERED,
            fingerprint=fingerprint,
            fingerprint_version=MCP_SERVER_FINGERPRINT_VERSION,
            created_at=ts,
            updated_at=ts,
            **body.model_dump(),
        )

    def to_public(self) -> "McpServerConfigPublic":
        return McpServerConfigPublic(
            server_id=self.server_id,
            name=self.name,
            server_slug=self.server_slug,
            transport=self.transport,
            stdio=_mask_stdio(self.stdio) if self.stdio else None,
            http=_mask_http(self.http) if self.http else None,
            provenance=self.provenance,
            approval_state=self.approval_state,
            tags=list(self.tags),
            notes=self.notes,
            fingerprint=self.fingerprint,
            fingerprint_version=self.fingerprint_version,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class McpServerConfigPublic(BaseModel):
    """Safe-to-return shape. ``stdio.env`` and ``http.headers`` values are
    masked. Never carries raw secrets.
    """

    model_config = ConfigDict(extra="forbid")

    server_id: str
    name: str
    server_slug: str
    transport: McpTransport
    stdio: McpStdioConfig | None = None
    """When present, env values are masked."""
    http: McpStreamableHttpConfig | None = None
    """When present, header values are masked."""
    provenance: McpProvenance
    approval_state: McpApprovalState
    tags: list[str]
    notes: str
    fingerprint: str
    fingerprint_version: str
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _mask_stdio(stdio: McpStdioConfig) -> McpStdioConfig:
    return McpStdioConfig(
        command=stdio.command,
        args=list(stdio.args),
        env={k: mask_env_value(v) for k, v in stdio.env.items()},
        env_refs=dict(stdio.env_refs),
        cwd_relative=stdio.cwd_relative,
    )


def _mask_http(http: McpStreamableHttpConfig) -> McpStreamableHttpConfig:
    return McpStreamableHttpConfig(
        url=http.url,
        headers={k: mask_env_value(v) for k, v in http.headers.items()},
        header_refs=dict(http.header_refs),
        timeout_seconds=http.timeout_seconds,
    )


def _compute_server_fingerprint(body: _McpServerBaseFields) -> str:
    """Versioned sha256 fingerprint over identity fields (analog of
    credentials.compute_credential_fingerprint).

    v2 (plan 2026-05-20 §Locked Revisions M4): includes env_refs / header_refs
    key names so adding a credential reference advances the fingerprint and
    invalidates any cached tool catalog. Values (credential_ids) are NOT
    part of the fingerprint — rotating which credential a ref points to
    must not advance the fingerprint, matching env-value rotation semantics.
    """
    import hashlib

    parts: list[str] = [
        MCP_SERVER_FINGERPRINT_VERSION,
        body.name.strip(),
        body.server_slug.strip(),
        body.transport.value,
    ]
    if body.stdio is not None:
        parts.append("stdio")
        parts.append(body.stdio.command)
        parts.extend(body.stdio.args)
        # env keys participate in identity (rotating a value alone shouldn't
        # change identity), env values do not — matches credential rotation
        # semantics.
        parts.extend(sorted(body.stdio.env.keys()))
        # env_refs participate the same way (v2). Key set change = identity
        # change; pointing the same env to a different credential_id is a
        # value-only change and does NOT bump fingerprint.
        if body.stdio.env_refs:
            parts.append("env_refs")
            parts.extend(sorted(body.stdio.env_refs.keys()))
    if body.http is not None:
        parts.append("http")
        parts.append(body.http.url)
        parts.extend(sorted(body.http.headers.keys()))
        if body.http.header_refs:
            parts.append("header_refs")
            parts.extend(sorted(body.http.header_refs.keys()))
    material = "\x00".join(parts).encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16]


__all__ = [
    "MCP_SERVER_FINGERPRINT_VERSION",
    "McpApprovalState",
    "McpProvenance",
    "McpServerConfig",
    "McpServerConfigCreate",
    "McpServerConfigPublic",
    "McpServerConfigUpdate",
    "McpStdioConfig",
    "McpStreamableHttpConfig",
    "McpToolCapability",
    "McpToolDescriptor",
    "McpTransport",
    "PendingMcpToolCall",
    "mask_env_value",
]
