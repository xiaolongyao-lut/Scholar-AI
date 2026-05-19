# -*- coding: utf-8 -*-
"""MCP Server registry HTTP API (Phase 1B / TASK-106).

Exposes:

  GET    /api/mcp/servers                    list_public
  POST   /api/mcp/servers                    create
  GET    /api/mcp/servers/{server_id}        get_public
  PUT    /api/mcp/servers/{server_id}        update (incl. approval state)
  DELETE /api/mcp/servers/{server_id}        delete (also tears down session)
  POST   /api/mcp/servers/{server_id}/test   connectivity probe (list_tools)
  GET    /api/mcp/servers/{server_id}/tools  cached tool catalog

Phase 2 will add tool execution; this router is registry + probe only.
Audit endpoint deferred to Phase 5.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from mcp_runtime.client_manager import (
    McpClientManager,
    McpClientManagerError,
    McpServerLaunchError,
    McpStreamableHttpDisabledError,
    get_mcp_client_manager,
)
from mcp_runtime.server_store import (
    McpApprovalTransitionError,
    McpServerNotFoundError,
    McpServerSchemaError,
    RuntimeMcpServerStore,
)
from mcp_runtime.tool_catalog import McpToolCatalog
from models.mcp import (
    McpServerConfigCreate,
    McpServerConfigPublic,
    McpServerConfigUpdate,
    McpToolDescriptor,
)


logger = logging.getLogger("McpRouter")
router = APIRouter(prefix="/api/mcp", tags=["MCP"])


# ---------------------------------------------------------------------------
# Module-level singletons (test-injectable)
# ---------------------------------------------------------------------------


_store: RuntimeMcpServerStore | None = None
_catalog: McpToolCatalog | None = None


def get_mcp_server_store() -> RuntimeMcpServerStore:
    global _store
    if _store is None:
        _store = RuntimeMcpServerStore()
    return _store


def set_mcp_server_store(store: RuntimeMcpServerStore | None) -> None:
    """Test hook: inject a tmp-path-backed store, or reset to default."""
    global _store
    _store = store


def get_mcp_tool_catalog() -> McpToolCatalog:
    global _catalog
    if _catalog is None:
        manager = get_mcp_client_manager()
        _catalog = McpToolCatalog(list_tools_fn=manager.list_tools)
    return _catalog


def set_mcp_tool_catalog(catalog: McpToolCatalog | None) -> None:
    global _catalog
    _catalog = catalog


# ---------------------------------------------------------------------------
# Registry CRUD
# ---------------------------------------------------------------------------


@router.get("/servers", response_model=list[McpServerConfigPublic])
async def list_servers(
    approval_state: str | None = None,
) -> list[McpServerConfigPublic]:
    """List MCP servers with masked env / headers. Optional filter by
    approval state.
    """
    from models.mcp import McpApprovalState
    store = get_mcp_server_store()
    state_filter = None
    if approval_state:
        try:
            state_filter = McpApprovalState(approval_state)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"unknown approval_state: {approval_state}"
            ) from exc
    try:
        return store.list_public(approval_state=state_filter)
    except McpServerSchemaError as exc:
        raise HTTPException(
            status_code=500, detail=f"mcp store schema error: {exc}"
        ) from exc


@router.post("/servers", response_model=McpServerConfigPublic)
async def create_server(body: McpServerConfigCreate) -> McpServerConfigPublic:
    store = get_mcp_server_store()
    try:
        return store.create(body)
    except ValueError as exc:
        # Includes duplicate server_slug + transport-block validation errors.
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/servers/{server_id}", response_model=McpServerConfigPublic)
async def get_server(server_id: str) -> McpServerConfigPublic:
    store = get_mcp_server_store()
    try:
        return store.get_public(server_id)
    except McpServerNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"mcp server not found: {server_id}"
        ) from exc


@router.put("/servers/{server_id}", response_model=McpServerConfigPublic)
async def update_server(
    server_id: str, body: McpServerConfigUpdate
) -> McpServerConfigPublic:
    store = get_mcp_server_store()
    catalog = get_mcp_tool_catalog()
    try:
        public = store.update(server_id, body)
    except McpApprovalTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except McpServerNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"mcp server not found: {server_id}"
        ) from exc
    # Config edit invalidates any cached tool catalog for this server.
    catalog.invalidate(server_id)
    return public


@router.delete("/servers/{server_id}")
async def delete_server(server_id: str) -> dict[str, Any]:
    store = get_mcp_server_store()
    catalog = get_mcp_tool_catalog()
    deleted = store.delete(server_id)
    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"mcp server not found: {server_id}"
        )
    # Per-operation sessions in Phase 1B → no live session to tear down.
    catalog.invalidate(server_id)
    return {"server_id": server_id, "deleted": True}


# ---------------------------------------------------------------------------
# Connectivity probe + cached catalog
# ---------------------------------------------------------------------------


@router.post("/servers/{server_id}/test")
async def test_server(server_id: str) -> dict[str, Any]:
    """Open a fresh session, list_tools, close session. Refreshes cache.
    Does NOT invoke any tool.

    Auto-promotes ``approval_state`` from ``registered`` to
    ``catalog_reviewed`` on first successful catalog fetch.
    """
    store = get_mcp_server_store()
    catalog = get_mcp_tool_catalog()

    try:
        config = store.get_internal(server_id)
    except McpServerNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"mcp server not found: {server_id}"
        ) from exc

    try:
        tools = await catalog.get_tools(config, refresh=True)
    except McpStreamableHttpDisabledError as exc:
        return {
            "server_id": server_id,
            "status": "skipped",
            "reason": str(exc),
            "probed": False,
        }
    except (McpServerLaunchError, McpClientManagerError) as exc:
        return {
            "server_id": server_id,
            "status": "probe_failed",
            "reason": f"{type(exc).__name__}: {exc}",
            "probed": True,
        }

    # On first successful probe, advance approval to catalog_reviewed.
    from models.mcp import McpApprovalState
    if config.approval_state == McpApprovalState.REGISTERED:
        store.update(
            server_id,
            McpServerConfigUpdate(approval_state=McpApprovalState.CATALOG_REVIEWED),
        )

    return {
        "server_id": server_id,
        "status": "ok",
        "tool_count": len(tools),
        "tools": [t.model_dump(mode="json") for t in tools],
        "fingerprint": catalog.fingerprint(server_id),
        "probed": True,
    }


@router.get("/servers/{server_id}/tools", response_model=list[McpToolDescriptor])
async def list_server_tools(server_id: str) -> list[McpToolDescriptor]:
    """Return the cached tool catalog for ``server_id``. If the cache is
    empty, runs a fresh list_tools to populate it.
    """
    store = get_mcp_server_store()
    catalog = get_mcp_tool_catalog()

    try:
        config = store.get_internal(server_id)
    except McpServerNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"mcp server not found: {server_id}"
        ) from exc

    try:
        return await catalog.get_tools(config)
    except McpStreamableHttpDisabledError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (McpServerLaunchError, McpClientManagerError) as exc:
        raise HTTPException(
            status_code=502, detail=f"mcp list_tools failed: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Audit (Phase 5 / TASK-502): read-only JSONL tail
# ---------------------------------------------------------------------------


@router.get("/audit")
async def list_audit(limit: int = 200) -> dict[str, Any]:
    """Tail the MCP tool-call audit log. Records are already redacted
    (security_policy.redact_text_for_audit on previews); this endpoint is
    read-only.
    """
    from mcp_runtime import audit as mcp_audit
    records = mcp_audit.read_recent(limit=limit)
    return {"count": len(records), "records": records}


# ---------------------------------------------------------------------------
# Pending-call protocol (Phase 3 / TASK-301)
# ---------------------------------------------------------------------------


@router.get("/pending-calls")
async def list_pending_calls() -> list[dict[str, Any]]:
    """Return all currently-pending MCP tool calls awaiting operator
    approval. Empty list when no pending — cheap poll target per the
    transport ADR.
    """
    from mcp_runtime.pending_calls import get_pending_call_store

    store = get_pending_call_store()
    return [p.model_dump(mode="json") for p in store.list_all()]


@router.post("/pending-calls/{call_id}/decide", status_code=204)
async def decide_pending_call(call_id: str, body: dict[str, Any]) -> None:
    """Record an operator decision for a pending MCP tool call.

    Body: ``{"decision": "approve" | "reject", "remember_for_run": bool}``.
    Returns 204 on success; 404 if the id is unknown / already decided /
    timed out; 400 on invalid body.
    """
    from mcp_runtime.pending_calls import get_pending_call_store

    decision = body.get("decision")
    if decision not in {"approve", "reject"}:
        raise HTTPException(
            status_code=400,
            detail="decision must be 'approve' or 'reject'",
        )
    remember_for_run = bool(body.get("remember_for_run", False))

    store = get_pending_call_store()
    try:
        store.decide(
            call_id,
            decision=decision,
            remember_for_run=remember_for_run,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"unknown_pending_call: {call_id}",
        ) from exc


__all__ = [
    "router",
    "set_mcp_server_store",
    "set_mcp_tool_catalog",
]
