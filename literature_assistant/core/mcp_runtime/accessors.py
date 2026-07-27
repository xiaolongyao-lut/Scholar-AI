"""
Convenience accessors for the MCP runtime layer.

These helpers wrap the most common one-liner queries operators and
integrations need ("is the X MCP server actually enabled right now?")
without forcing every caller to import McpServerStore and read its
internal representation. Lookup is by slug, the stable identifier that
catalog descriptors and integration plans (e.g. the Vision Auxiliary
P0 plan, which calls `has_enabled_server("vision-auxiliary")`) use.

For vision integrations, "enabled" is defined
strictly as `approval_state == ENABLED_FOR_SESSION`. Registered and
catalog-reviewed servers are treated as DISABLED — the helper must not
accept them as "good enough" because tool execution requires the full
approval handshake.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from literature_assistant.core.mcp_runtime.server_store import RuntimeMcpServerStore
    from literature_assistant.core.models.mcp import McpApprovalState, McpServerConfig
else:
    from mcp_runtime.server_store import RuntimeMcpServerStore
    from models.mcp import McpApprovalState, McpServerConfig


def _resolve_server(
    slug: str,
    *,
    store: Optional[RuntimeMcpServerStore] = None,
) -> Optional[McpServerConfig]:
    """Return the first server whose `server_slug` matches, or None.

    `slug` matching is case-sensitive — slugs are stable kebab-case
    identifiers and the catalog enforces that at create time.
    """

    if not slug:
        return None
    active_store = store or RuntimeMcpServerStore()
    for server in active_store.list_internal():
        # Canonical and legacy imports can give the same model distinct identities.
        server_slug = getattr(server, "server_slug", None)
        approval_state = getattr(server, "approval_state", None)
        if not isinstance(server_slug, str) or approval_state is None:
            continue
        if server_slug == slug:
            return server
    return None


def has_enabled_server(
    slug: str,
    *,
    store: Optional[RuntimeMcpServerStore] = None,
) -> bool:
    """Return True iff a server with this slug exists AND its
    approval_state is ENABLED_FOR_SESSION.

    Use this before invoking a server's tools to make sure the operator
    has gone through the full approval handshake. The check fails closed:
    missing server, mismatched approval state, or persistence failures all
    return False (the caller must treat the server as unavailable, not
    crash).

    Args:
        slug: server_slug to look up (the kebab-case identifier).
        store: optional injected store; defaults to a fresh
            RuntimeMcpServerStore() reading the canonical persistence path.

    Examples:
        >>> has_enabled_server("vision-auxiliary")  # in production
        False  # until the operator approves the server
    """

    try:
        server = _resolve_server(slug, store=store)
    except Exception:
        return False
    if server is None:
        return False
    return server.approval_state == McpApprovalState.ENABLED_FOR_SESSION


def get_enabled_server(
    slug: str,
    *,
    store: Optional[RuntimeMcpServerStore] = None,
) -> Optional[McpServerConfig]:
    """Return an enabled server config for tool execution, or None.

    This is the config-returning counterpart to `has_enabled_server`.
    It preserves the same fail-closed approval semantics: callers only
    receive a server when it exists and approval_state is ENABLED_FOR_SESSION.
    """

    try:
        server = _resolve_server(slug, store=store)
    except Exception:
        return None
    if server is None:
        return None
    if server.approval_state != McpApprovalState.ENABLED_FOR_SESSION:
        return None
    return server
