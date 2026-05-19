"""Runtime override for rerank backend configuration.

Thin wrapper around :mod:`model_config_store` for backwards compatibility.
All existing callers (``reranker_client``, ``rerank_config_router``) continue
to work unchanged via the module-level functions below.

Schema (unchanged)::

    {
      "provider": "siliconflow" | "dashscope" | "custom",
      "base_url": "https://api.siliconflow.cn/v1/rerank",
      "api_key": "sk-...",
      "model": "bge-reranker-v2-m3",
      "updated_at": "2026-05-13T03:42:11Z"
    }
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from model_config_store import rerank_store

# Backwards-compatible: tests monkeypatch rerank_runtime_config._OVERRIDE_PATH
# to redirect file I/O to a temp path. We intercept that via a module wrapper
# so the underlying store's _path is updated in sync.
_OVERRIDE_PATH = rerank_store._path


def get_public_config() -> dict[str, Any]:
    """Return the override fields safe to surface to the UI (api_key masked)."""
    return rerank_store.get_public_config()


def get_resolved_field(name: str) -> str | None:
    """Return the raw override value for ``name`` or None."""
    return rerank_store.get_resolved_field(name)


def write_config(
    *,
    provider: str | None,
    base_url: str | None,
    api_key: str | None,
    model: str | None,
) -> dict[str, Any]:
    """Atomically write the override document."""
    return rerank_store.write_config(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
    )


def clear_config() -> None:
    """Remove the override file."""
    rerank_store.clear_config()


class _OverridePathProxy:
    """Module wrapper that syncs _OVERRIDE_PATH setattr to rerank_store._path."""

    def __init__(self, module):
        object.__setattr__(self, '_module', module)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, '_module'), name)

    def __setattr__(self, name, value):
        if name == '_OVERRIDE_PATH':
            rerank_store._path = Path(value) if not isinstance(value, Path) else value
            setattr(object.__getattribute__(self, '_module'), name, value)
        else:
            setattr(object.__getattribute__(self, '_module'), name, value)


sys.modules[__name__] = _OverridePathProxy(sys.modules[__name__])  # type: ignore[assignment]

__all__ = [
    "get_public_config",
    "get_resolved_field",
    "write_config",
    "clear_config",
    "_OVERRIDE_PATH",
]
