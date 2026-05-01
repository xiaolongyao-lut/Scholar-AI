from __future__ import annotations

from datetime import datetime, timezone


UTC_SUFFIX = "Z"


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def utc_timestamp() -> int:
    """Return the current UTC timestamp in whole seconds."""
    return int(utc_now().timestamp())


def ensure_utc(value: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_iso_z(value: datetime | str) -> str:
    """Render a datetime or ISO string with a trailing Z suffix."""
    if isinstance(value, datetime):
        value = ensure_utc(value).isoformat()
    if value.endswith("+00:00"):
        return value[:-6] + UTC_SUFFIX
    return value


def utc_now_iso() -> str:
    """Return the current UTC time in ISO 8601 format."""
    return utc_now().isoformat()


def utc_now_iso_z() -> str:
    """Return the current UTC time in ISO 8601 format with Z suffix."""
    return to_iso_z(utc_now())


def utc_now_naive() -> datetime:
    """Return the current UTC datetime without tzinfo for legacy tests."""
    return utc_now().replace(tzinfo=None)


def ensure_z_suffix(timestamp: str) -> str:
    """Ensure a timestamp string uses the Z suffix for UTC."""
    return to_iso_z(timestamp)