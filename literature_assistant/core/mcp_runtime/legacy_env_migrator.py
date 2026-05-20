"""Legacy raw-secret detector + env→ref migration (S6 / plan 2026-05-20 §6).

Heuristic-based detector for ``McpStdioConfig.env`` and
``McpStreamableHttpConfig.headers`` entries that look like API keys but
predate the env_refs / header_refs design. Used by the frontend's
installed-view legacy banner and the migration endpoint.

Rules (intentionally conservative — false positives push the user toward
the migration UI, which then asks for explicit confirmation, so over-
flagging is safer than under-flagging):

- Key matches ``API_KEY / TOKEN / SECRET / PASSWORD / BEARER / *_KEY$``
  case-insensitively
- Value is non-empty after strip and not a tiny placeholder ("1" / "true" /
  "false" / single digit)
"""

from __future__ import annotations

import re
from dataclasses import dataclass


SECRET_KEY_RE = re.compile(
    r"(API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|BEARER|AUTHORIZATION|_KEY$|KEY$)",
    re.IGNORECASE,
)

_TINY_PLACEHOLDER = frozenset({"", "1", "0", "true", "false", "yes", "no", "on", "off"})


@dataclass(frozen=True, slots=True)
class LegacyRawSecret:
    """One env / header entry that looks like a raw secret.

    Used by the migration UI to render the per-key picker. ``value_masked``
    is the same masking applied by the public API so the UI never receives
    a raw value here.
    """

    target_env: str
    value_masked: str
    transport_field: str  # "stdio.env" | "http.headers"


def detect_legacy_secrets(
    *,
    stdio_env: dict[str, str] | None,
    stdio_env_refs: dict[str, str] | None,
    http_headers: dict[str, str] | None,
    http_header_refs: dict[str, str] | None,
) -> list[LegacyRawSecret]:
    """Return raw-secret-shaped entries that are NOT already covered by refs.

    Callers pass the *internal* MCP config view (raw values) because we
    apply masking in this module — the result never carries the raw
    plaintext upstream.
    """
    out: list[LegacyRawSecret] = []
    ref_keys = set((stdio_env_refs or {}).keys())
    for k, v in (stdio_env or {}).items():
        if k in ref_keys:
            continue
        if _looks_like_raw_secret(k, v):
            out.append(LegacyRawSecret(
                target_env=k,
                value_masked=_mask(v),
                transport_field="stdio.env",
            ))
    ref_header_keys = set((http_header_refs or {}).keys())
    for k, v in (http_headers or {}).items():
        if k in ref_header_keys:
            continue
        if _looks_like_raw_secret(k, v):
            out.append(LegacyRawSecret(
                target_env=k,
                value_masked=_mask(v),
                transport_field="http.headers",
            ))
    return out


def _looks_like_raw_secret(key: str, value: str) -> bool:
    if not key or not isinstance(value, str):
        return False
    if value.strip().lower() in _TINY_PLACEHOLDER:
        return False
    return bool(SECRET_KEY_RE.search(key))


def _mask(value: str) -> str:
    """Local copy of the public mask shape (mirror of mask_env_value)."""
    if not value:
        return ""
    s = value.strip()
    if len(s) <= 8:
        return "***"
    return f"{s[:4]}...{s[-4:]}"


__all__ = [
    "LegacyRawSecret",
    "SECRET_KEY_RE",
    "detect_legacy_secrets",
]
