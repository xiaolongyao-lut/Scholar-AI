"""Runtime credential models (Slice A1, plan v2 §3.2.7 / DEC-007).

Two identity concepts coexist (DEC-007a):
    - credential_id (UUID4): UI / CRUD / selection identity. Stable across
      renames or fingerprint version bumps.
    - credential_fingerprint: cooldown / health identity. Versioned sha256 of
      provider + normalized base_url + model + sha256(api_key). Bumping the
      version prefix intentionally resets cooldown state (DEC-007b).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


CREDENTIAL_FINGERPRINT_VERSION = "v1"


class CredentialCategory(str, Enum):
    GENERATION = "generation"
    EMBEDDING = "embedding"
    RERANK = "rerank"


class CredentialProtocol(str, Enum):
    OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"
    OPENAI_RESPONSES = "openai_responses"
    ANTHROPIC_MESSAGES = "anthropic_messages"
    EMBEDDINGS = "embeddings"
    RERANK = "rerank"


class CredentialStrategyHint(str, Enum):
    """Cost/quality tier hints for credential selection.

    Canonical product tiers (B5 decision 2026-05-26):
        LOW, MEDIUM, HIGH, XHIGH, MAX

    Legacy compatibility values (preserved for existing callers):
        DEFAULT, CHEAP, FAST, QUALITY

    Surface-specific hints (not cost tiers):
        DISCUSSION, EMBEDDING, RERANK
    """
    # Canonical product tiers
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"

    # Legacy compatibility (map to canonical via normalize_strategy_hint)
    DEFAULT = "default"
    CHEAP = "cheap"
    FAST = "fast"
    QUALITY = "quality"

    # Surface-specific hints
    DISCUSSION = "discussion"
    EMBEDDING = "embedding"
    RERANK = "rerank"


class CredentialTrustSource(str, Enum):
    """plan v2 §4.4 — 4-tier trust hierarchy."""

    OFFICIAL_PROVIDER = "official_provider"
    ENV_CONFIGURED_GATEWAY = "env_configured_gateway"
    RUNTIME_USER_CONFIRMED = "runtime_user_confirmed"
    RUNTIME_UNTRUSTED_CUSTOM = "runtime_untrusted_custom"


class SamplingParams(BaseModel):
    """Optional per-credential generation controls.

    All fields are nullable so existing credentials can omit the block and
    callers can override one sampling key without copying unrelated defaults.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=1, le=32_768)
    system_prompt: str | None = Field(default=None, max_length=8192)

    def to_sampling_dict(self) -> dict[str, float | int]:
        """Return only numeric keys accepted by task sampling resolvers."""
        out: dict[str, float | int] = {}
        if self.temperature is not None:
            out["temperature"] = self.temperature
        if self.top_p is not None:
            out["top_p"] = self.top_p
        if self.max_tokens is not None:
            out["max_tokens"] = self.max_tokens
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCHEME_HOST_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*)://([^/?#]+)(.*)$")


def normalize_base_url(url: str) -> str:
    """Normalize a base_url for fingerprint computation (DEC-007a).

    - Lowercase scheme + host
    - Strip trailing slash on path
    - No default port stripping (explicit port preserved)
    - Reject query / fragment (must be path-only base URL)
    """
    if not url:
        return ""
    cleaned = url.strip()
    if "?" in cleaned or "#" in cleaned:
        raise ValueError(f"base_url must not contain query or fragment: {url!r}")
    m = _SCHEME_HOST_RE.match(cleaned)
    if not m:
        # Lenient: allow callers to pass a host-only string; just lowercase.
        return cleaned.lower().rstrip("/")
    scheme, hostport, rest = m.group(1).lower(), m.group(2).lower(), m.group(3)
    rest = rest.rstrip("/")
    return f"{scheme}://{hostport}{rest}"


def compute_credential_fingerprint(
    *,
    provider: str,
    base_url: str,
    model: str,
    api_key: str,
) -> str:
    """Versioned sha256 fingerprint for cooldown / health identity (DEC-007a).

    Identity sources: provider + normalized base_url + model + sha256(api_key).
    Bumping CREDENTIAL_FINGERPRINT_VERSION intentionally invalidates all
    cooldown state (DEC-007b).
    """
    norm_url = normalize_base_url(base_url)
    api_key_hash = hashlib.sha256((api_key or "").strip().encode("utf-8")).hexdigest()
    parts = [
        CREDENTIAL_FINGERPRINT_VERSION,
        (provider or "").strip(),
        norm_url,
        (model or "").strip(),
        api_key_hash,
    ]
    material = "\x00".join(parts).encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16]


def mask_api_key(value: str) -> str:
    """Return a masked form safe for public API responses.

    Empty -> empty. Short keys -> `***`. Otherwise prefix(4) + ... + suffix(4).
    """
    if not value:
        return ""
    s = value.strip()
    if len(s) <= 8:
        return "***"
    return f"{s[:4]}...{s[-4:]}"


def normalize_strategy_hint(value: str | CredentialStrategyHint | None) -> CredentialStrategyHint:
    """Normalize legacy/canonical strategy hints to canonical product tiers.

    B5 decision 2026-05-26: Accept old values, return canonical five-tier.

    Mapping:
        cheap -> low
        default -> medium
        fast -> medium (preserves latency hint semantics)
        quality -> high
        xhigh -> xhigh
        max -> max

    Surface-specific hints (discussion/embedding/rerank) pass through unchanged.
    Unknown values default to MEDIUM.
    """
    if value is None:
        return CredentialStrategyHint.MEDIUM

    if isinstance(value, CredentialStrategyHint):
        raw = value.value
    else:
        raw = str(value).strip().lower()

    # Canonical tiers
    if raw in {"low", "medium", "high", "xhigh", "max"}:
        return CredentialStrategyHint(raw)

    # Legacy compatibility
    if raw in {"cheap", "save", "aggressive", "cost-save", "cost_save"}:
        return CredentialStrategyHint.LOW
    if raw in {"default", "balanced"}:
        return CredentialStrategyHint.MEDIUM
    if raw == "fast":
        return CredentialStrategyHint.MEDIUM
    if raw in {"quality", "high-quality", "high_quality"}:
        return CredentialStrategyHint.HIGH

    # Surface-specific hints
    if raw in {"discussion", "embedding", "rerank"}:
        return CredentialStrategyHint(raw)

    # Unknown -> default
    return CredentialStrategyHint.MEDIUM


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Public-facing API models
# ---------------------------------------------------------------------------


class _CredentialBaseFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    category: CredentialCategory
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    base_url: str = Field(min_length=1, max_length=512)
    protocol: CredentialProtocol
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10_000)
    tags: list[str] = Field(default_factory=list)
    strategy_hint: CredentialStrategyHint = CredentialStrategyHint.DEFAULT
    trust_source: CredentialTrustSource = CredentialTrustSource.RUNTIME_UNTRUSTED_CUSTOM
    notes: str = Field(default="", max_length=1024)
    sampling_override: SamplingParams | None = None

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, v: str) -> str:
        # Will raise if query/fragment present.
        normalize_base_url(v)
        return v


class RuntimeCredentialCreate(_CredentialBaseFields):
    """Body of POST /api/credentials. Carries the secret only on input."""

    api_key: str = Field(min_length=1, max_length=512)


class RuntimeCredentialUpdate(BaseModel):
    """Body of PUT /api/credentials/{id}. All fields optional; api_key is
    accepted only when explicitly rotating.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provider: str | None = Field(default=None, min_length=1, max_length=64)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    base_url: str | None = Field(default=None, min_length=1, max_length=512)
    protocol: CredentialProtocol | None = None
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10_000)
    tags: list[str] | None = None
    strategy_hint: CredentialStrategyHint | None = None
    trust_source: CredentialTrustSource | None = None
    notes: str | None = Field(default=None, max_length=1024)
    sampling_override: SamplingParams | None = Field(default=None)
    api_key: str | None = Field(default=None, min_length=1, max_length=512)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, v: str | None) -> str | None:
        if v is not None:
            normalize_base_url(v)
        return v


class RuntimeCredential(_CredentialBaseFields):
    """Full domain model with secret. Persisted in the runtime store; never
    serialized to public API responses (use RuntimeCredentialPublic instead).
    """

    credential_id: str
    api_key: str = Field(min_length=1, max_length=512)
    fingerprint: str
    fingerprint_version: str = CREDENTIAL_FINGERPRINT_VERSION
    created_at: str
    updated_at: str

    @classmethod
    def from_create(cls, body: RuntimeCredentialCreate) -> "RuntimeCredential":
        ts = _utc_now_iso()
        cid = f"cred_{uuid.uuid4().hex[:16]}"
        fingerprint = compute_credential_fingerprint(
            provider=body.provider,
            base_url=body.base_url,
            model=body.model,
            api_key=body.api_key,
        )
        body_dict = body.model_dump(exclude={'api_key'})
        return cls(
            credential_id=cid,
            api_key=body.api_key,
            fingerprint=fingerprint,
            fingerprint_version=CREDENTIAL_FINGERPRINT_VERSION,
            created_at=ts,
            updated_at=ts,
            **body_dict,
        )

    def with_update(self, body: RuntimeCredentialUpdate) -> "RuntimeCredential":
        """Return an updated copy. Recomputes fingerprint if any identity
        field (provider/base_url/model/api_key) changed.
        """
        dumped_update = body.model_dump(exclude_unset=True)
        update = {
            key: value
            for key, value in dumped_update.items()
            if value is not None or key == "sampling_override"
        }
        merged = self.model_dump()
        merged.update(update)
        identity_changed = any(
            k in update for k in ("provider", "base_url", "model", "api_key")
        )
        if identity_changed:
            merged["fingerprint"] = compute_credential_fingerprint(
                provider=merged["provider"],
                base_url=merged["base_url"],
                model=merged["model"],
                api_key=merged["api_key"],
            )
            merged["fingerprint_version"] = CREDENTIAL_FINGERPRINT_VERSION
        merged["updated_at"] = _utc_now_iso()
        return RuntimeCredential(**merged)

    def to_public(self) -> "RuntimeCredentialPublic":
        return RuntimeCredentialPublic(
            credential_id=self.credential_id,
            category=self.category,
            provider=self.provider,
            model=self.model,
            base_url=self.base_url,
            protocol=self.protocol,
            enabled=self.enabled,
            priority=self.priority,
            tags=list(self.tags),
            strategy_hint=normalize_strategy_hint(self.strategy_hint),
            trust_source=self.trust_source,
            notes=self.notes,
            sampling_override=self.sampling_override,
            api_key_masked=mask_api_key(self.api_key),
            has_api_key=bool(self.api_key),
            fingerprint=self.fingerprint,
            fingerprint_version=self.fingerprint_version,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class RuntimeCredentialPublic(BaseModel):
    """Safe-to-return shape. Never includes raw api_key."""

    model_config = ConfigDict(extra="forbid")

    credential_id: str
    category: CredentialCategory
    provider: str
    model: str
    base_url: str
    protocol: CredentialProtocol
    enabled: bool
    priority: int
    tags: list[str]
    strategy_hint: CredentialStrategyHint
    trust_source: CredentialTrustSource
    notes: str
    sampling_override: SamplingParams | None = None
    api_key_masked: str
    has_api_key: bool
    fingerprint: str
    fingerprint_version: str
    created_at: str
    updated_at: str


__all__ = [
    "CREDENTIAL_FINGERPRINT_VERSION",
    "CredentialCategory",
    "CredentialProtocol",
    "CredentialStrategyHint",
    "CredentialTrustSource",
    "RuntimeCredential",
    "RuntimeCredentialCreate",
    "RuntimeCredentialPublic",
    "RuntimeCredentialUpdate",
    "SamplingParams",
    "compute_credential_fingerprint",
    "mask_api_key",
    "normalize_base_url",
]
