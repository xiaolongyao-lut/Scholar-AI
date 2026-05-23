"""Generic feature flag registry with override persistence + env fallback.

Resolution priority for each registered flag:
  1. ``runtime_state/feature_flags_override.json`` (UI-writable via API)
  2. Environment variable (legacy / dev override)
  3. Registered default

The registry (``FEATURE_FLAGS``) is the single source of truth for which flags
exist; arbitrary keys in the override file are ignored. Add new flags by
appending a ``FeatureFlagSpec`` to ``FEATURE_FLAGS``.

Atomic writes (tempfile + ``os.replace``) mirror ``model_config_store`` so a
crash mid-write cannot corrupt the override document.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from project_paths import runtime_state_path


_TRUTHY_VALUES: frozenset[str] = frozenset({"1", "true", "yes", "on", "y"})


def _truthy(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    return str(raw).strip().lower() in _TRUTHY_VALUES


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class FeatureFlagSpec:
    """Static metadata for a feature flag exposed to the Settings UI."""

    name: str
    default: bool
    env_var: Optional[str]
    label: str
    description: str


FEATURE_FLAGS: dict[str, FeatureFlagSpec] = {
    "tolf_context": FeatureFlagSpec(
        name="tolf_context",
        default=False,
        env_var="INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED",
        label="TOLF 目标导向检索",
        description=(
            "实验性检索：把问题拆成多面查询、在文献图上扩散、按硬证据筛选。"
            "比默认 RAG 更慢，但找间接证据、归因清晰、抗弱化措辞。"
            "适合综述、找数据、深度调研。同一问题分别开/关跑一次可直观对比。"
        ),
    ),
}


_OVERRIDE_PATH: Path = runtime_state_path("feature_flags_override.json")
_LOCK = threading.Lock()


def _read_overrides() -> dict[str, bool]:
    try:
        with open(_OVERRIDE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    flags = data.get("flags")
    if not isinstance(flags, dict):
        return {}
    return {k: bool(v) for k, v in flags.items() if isinstance(k, str)}


def _write_overrides_atomic(overrides: dict[str, bool]) -> None:
    if not overrides:
        try:
            _OVERRIDE_PATH.unlink()
        except FileNotFoundError:
            pass
        return
    payload = {"flags": overrides, "updated_at": _now_iso()}
    _OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix="feature_flags_override_",
        suffix=".json.tmp",
        dir=str(_OVERRIDE_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, _OVERRIDE_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _resolve(spec: FeatureFlagSpec, overrides: dict[str, bool]) -> tuple[bool, str]:
    if spec.name in overrides:
        return bool(overrides[spec.name]), "override"
    if spec.env_var:
        env_val = os.getenv(spec.env_var)
        if env_val is not None and env_val.strip():
            return _truthy(env_val), "env"
    return spec.default, "default"


def is_enabled(name: str) -> bool:
    """Resolve a feature flag. Unknown flags return False."""
    spec = FEATURE_FLAGS.get(name)
    if spec is None:
        return False
    current, _ = _resolve(spec, _read_overrides())
    return current


def list_flags() -> list[dict[str, Any]]:
    """Return every registered flag with metadata + currently resolved value."""
    overrides = _read_overrides()
    out: list[dict[str, Any]] = []
    for spec in FEATURE_FLAGS.values():
        current, source = _resolve(spec, overrides)
        out.append(
            {
                "name": spec.name,
                "label": spec.label,
                "description": spec.description,
                "default": spec.default,
                "env_var": spec.env_var,
                "current": current,
                "source": source,
            }
        )
    return out


def set_flag(name: str, enabled: bool) -> dict[str, Any]:
    """Persist an override for a registered flag. Returns the resolved entry."""
    if name not in FEATURE_FLAGS:
        raise KeyError(f"unknown feature flag: {name}")
    with _LOCK:
        overrides = _read_overrides()
        overrides[name] = bool(enabled)
        _write_overrides_atomic(overrides)
    return next(f for f in list_flags() if f["name"] == name)


__all__ = [
    "FeatureFlagSpec",
    "FEATURE_FLAGS",
    "is_enabled",
    "list_flags",
    "set_flag",
]
