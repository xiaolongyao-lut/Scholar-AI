"""Shared plaintext-secret guards for local extension configuration."""

from __future__ import annotations

import re
from typing import Mapping, Sequence


_SEPARATOR_PATTERN = re.compile(r"[^a-z0-9]+")
_SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:Bearer|Token)\s+[A-Za-z0-9._\-+/=]{16,}", re.IGNORECASE),
    re.compile(
        r"\b(?:sk|pk|key|xoxb|xoxp|ghp|github_pat)-[A-Za-z0-9_\-]{12,}\b",
        re.IGNORECASE,
    ),
)
_SECRET_NAME_TERMS = frozenset(
    {
        "api_key",
        "apikey",
        "secret",
        "password",
        "passwd",
        "credential",
        "authorization",
        "bearer",
        "oauth",
        "access_key",
        "密钥",
        "令牌",
        "密码",
        "访问凭证",
    }
)
_SAFE_TOKEN_TERMS = frozenset(
    {
        "token_limit",
        "max_token",
        "max_tokens",
        "token_budget",
        "token_count",
        "token_window",
        "token_length",
        "token_usage",
    }
)


def is_secret_field_name(value: str) -> bool:
    """Return whether a config field name appears to request credential material.

    Args:
        value: Field id, env name, label, or description text.

    Returns:
        ``True`` when the text should be represented as a credential reference
        rather than a persisted plaintext config value.
    """
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    text = value.strip()
    if not text:
        return False
    lowered = text.lower()
    if any(term in lowered for term in ("密钥", "令牌", "密码", "访问凭证")):
        return True
    normalized = _SEPARATOR_PATTERN.sub("_", lowered).strip("_")
    if not normalized:
        return False
    if any(term in normalized for term in _SECRET_NAME_TERMS if term.isascii()):
        return True
    if "token" in normalized and not any(term in normalized for term in _SAFE_TOKEN_TERMS):
        return True
    return False


def looks_like_secret_value(value: str) -> bool:
    """Return whether a string value has a credential-like token shape.

    Args:
        value: Plain config value supplied by a manifest or runtime settings UI.

    Returns:
        ``True`` for common provider key and bearer-token shapes. The matcher is
        intentionally narrow to avoid treating ordinary endpoint/model strings
        as secrets.
    """
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    text = value.strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _SECRET_VALUE_PATTERNS)


def is_plaintext_secret_config_field(
    *,
    field_id: str,
    label: str,
    env: str,
    description: str = "",
    default: str | None = None,
) -> bool:
    """Return whether a config field should be converted to a credential slot.

    Args:
        field_id: Stable config-field id.
        label: User-facing label.
        env: Environment variable name produced by the field.
        description: Optional field help text.
        default: Optional plaintext default from a manifest.

    Returns:
        ``True`` when persisting this field as ordinary config would risk saving
        credential material.
    """
    for candidate in (field_id, label, env, description):
        if candidate and is_secret_field_name(candidate):
            return True
    return default is not None and looks_like_secret_value(default)


def find_plaintext_secret_config_entries(values: Mapping[str, str]) -> list[str]:
    """Return config keys whose names or values look like plaintext secrets.

    Args:
        values: Non-sensitive runtime config values keyed by env name.

    Returns:
        Sorted offending keys. Callers should reject these values and require
        saved-credential references instead.
    """
    if not isinstance(values, Mapping):
        raise TypeError("values must be a mapping")
    offenders: list[str] = []
    for key, value in values.items():
        if not isinstance(key, str) or not isinstance(value, str):
            offenders.append(str(key))
            continue
        if is_secret_field_name(key) or looks_like_secret_value(value):
            offenders.append(key)
    return sorted(set(offenders))


def require_no_plaintext_secret_config(values: Mapping[str, str]) -> None:
    """Raise ``ValueError`` when non-sensitive config values contain secrets.

    Args:
        values: Non-sensitive config values keyed by env name.

    Raises:
        ValueError: A credential-shaped value or credential-like key was found.
    """
    offenders = find_plaintext_secret_config_entries(values)
    if offenders:
        joined = ", ".join(offenders)
        raise ValueError(
            "Plaintext credential material is not allowed in config_values; "
            f"use credential_bindings for: {joined}"
        )


def find_plaintext_secret_field_indexes(fields: Sequence[Mapping[str, object]]) -> list[int]:
    """Return config-field indexes that should be credential declarations.

    Args:
        fields: Raw manifest ``config_fields`` entries.

    Returns:
        Indexes whose id/label/env/description/default indicate a credential.
    """
    if not isinstance(fields, Sequence) or isinstance(fields, (str, bytes)):
        raise TypeError("fields must be a sequence")
    indexes: list[int] = []
    for index, field in enumerate(fields):
        if not isinstance(field, Mapping):
            continue
        default_raw = field.get("default")
        default = None if default_raw is None else str(default_raw)
        if is_plaintext_secret_config_field(
            field_id=str(field.get("id", "") or ""),
            label=str(field.get("label", "") or ""),
            env=str(field.get("env", "") or ""),
            description=str(field.get("description", "") or ""),
            default=default,
        ):
            indexes.append(index)
    return indexes


__all__ = [
    "find_plaintext_secret_config_entries",
    "find_plaintext_secret_field_indexes",
    "is_plaintext_secret_config_field",
    "is_secret_field_name",
    "looks_like_secret_value",
    "require_no_plaintext_secret_config",
]
