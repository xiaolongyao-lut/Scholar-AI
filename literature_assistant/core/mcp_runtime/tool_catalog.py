"""Tool catalog cache (Phase 1B / TASK-105).

Per-server cache of ``list_tools()`` results with content-fingerprint
invalidation. Phase 1B exposes:

  - ``get_tools(config, refresh=False)`` → cached list[McpToolDescriptor]
  - ``invalidate(server_id)`` → drop cache entry (called on config edit)
  - ``invalidate_all()`` → drop everything (called on bulk reload)
  - cached entries carry a sha256 fingerprint over (name, description,
    input_schema) so a diff audit can detect tool churn between refreshes

Phase 2+ may add:
  - TTL-based auto-refresh (plan v0.3 §3.2 Q8a+ — 10 min)
  - ``tools/list_changed`` notification subscription via mcp SDK
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from models.mcp import McpServerConfig, McpToolDescriptor


logger = logging.getLogger("McpToolCatalog")


# ListToolsFn(config) -> list[McpToolDescriptor]
ListToolsFn = Callable[[McpServerConfig], Awaitable[list[McpToolDescriptor]]]


@dataclass
class _CacheEntry:
    tools: list[McpToolDescriptor] = field(default_factory=list)
    fingerprint: str = ""


def _fingerprint_tools(tools: list[McpToolDescriptor]) -> str:
    """Stable sha256 over (name, description, input_schema) for each tool,
    sorted by name. 16-char hex prefix matches credential / mcp server
    fingerprint format.
    """
    payload: list[dict] = []
    for t in sorted(tools, key=lambda x: x.name):
        payload.append({
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        })
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


class McpToolCatalog:
    """Per-server tool descriptor cache.

    The fetcher takes a full ``McpServerConfig`` (not just server_id)
    because Phase 1B uses per-operation sessions — the catalog hands the
    config to the manager, the manager opens a fresh session for the
    list_tools call.
    """

    def __init__(self, list_tools_fn: ListToolsFn) -> None:
        self._list_tools = list_tools_fn
        self._cache: dict[str, _CacheEntry] = {}

    async def get_tools(
        self,
        config: McpServerConfig,
        *,
        refresh: bool = False,
    ) -> list[McpToolDescriptor]:
        """Return cached tools for ``config.server_id``. Fetches and
        caches if absent or ``refresh=True``. On refresh, logs a diff
        if the fingerprint changed.
        """
        server_id = config.server_id
        cached = self._cache.get(server_id)
        if cached is not None and not refresh:
            return list(cached.tools)

        fresh = await self._list_tools(config)
        new_fp = _fingerprint_tools(fresh)
        if cached is not None and cached.fingerprint != new_fp:
            old_names = {t.name for t in cached.tools}
            new_names = {t.name for t in fresh}
            added = sorted(new_names - old_names)
            removed = sorted(old_names - new_names)
            logger.info(
                "mcp_runtime.tool_catalog server=%s catalog changed "
                "(fp %s -> %s) added=%s removed=%s",
                server_id, cached.fingerprint, new_fp, added, removed,
            )
        self._cache[server_id] = _CacheEntry(
            tools=list(fresh),
            fingerprint=new_fp,
        )
        return list(fresh)

    def fingerprint(self, server_id: str) -> str | None:
        """Return current cached fingerprint or None if uncached."""
        cached = self._cache.get(server_id)
        return cached.fingerprint if cached else None

    def invalidate(self, server_id: str) -> bool:
        """Drop one server's cache entry. Returns True if dropped."""
        return self._cache.pop(server_id, None) is not None

    def invalidate_all(self) -> int:
        """Drop everything. Returns the number of entries removed."""
        n = len(self._cache)
        self._cache.clear()
        return n


__all__ = [
    "ListToolsFn",
    "McpToolCatalog",
]
