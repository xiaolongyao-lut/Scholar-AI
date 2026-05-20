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
    install_record_deleted = False
    try:
        from mcp_runtime.template_installer import get_template_installer

        install_record_deleted = get_template_installer().cleanup_install_dir(server_id)
    except RuntimeError:
        install_record_deleted = False
    return {
        "server_id": server_id,
        "deleted": True,
        "install_record_deleted": install_record_deleted,
    }


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
# Legacy raw-env detection + migration (S6 / plan 2026-05-20 §6)
# ---------------------------------------------------------------------------


@router.get("/servers/{server_id}/legacy-env")
async def list_legacy_env(server_id: str) -> dict[str, Any]:
    """Detect raw-secret-shaped env / header entries on a server.

    Returns masked values only — the raw plaintext never crosses this
    boundary. Caller (frontend installed-view banner) uses the result to
    show a migration prompt; the actual move happens via the POST
    ``/migrate-env-to-refs`` endpoint below.
    """
    from mcp_runtime.legacy_env_migrator import detect_legacy_secrets

    store = get_mcp_server_store()
    try:
        config = store.get_internal(server_id)
    except McpServerNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"mcp server not found: {server_id}"
        ) from exc
    stdio_env = dict(config.stdio.env) if config.stdio else None
    stdio_env_refs = dict(config.stdio.env_refs) if config.stdio else None
    http_headers = dict(config.http.headers) if config.http else None
    http_header_refs = dict(config.http.header_refs) if config.http else None
    detected = detect_legacy_secrets(
        stdio_env=stdio_env,
        stdio_env_refs=stdio_env_refs,
        http_headers=http_headers,
        http_header_refs=http_header_refs,
    )
    return {
        "server_id": server_id,
        "count": len(detected),
        "entries": [
            {
                "target_env": d.target_env,
                "value_masked": d.value_masked,
                "transport_field": d.transport_field,
            }
            for d in detected
        ],
    }


@router.post("/servers/{server_id}/migrate-env-to-refs")
async def migrate_env_to_refs(
    server_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Move raw env / header values into env_refs / header_refs.

    Body schema:
        {
          "mapping": {"<env_key>": "<credential_id>", ...},
          "confirm_remove_raw": true
        }

    Validation:
    - Every credential_id in ``mapping`` must exist + be enabled.
    - Every ``env_key`` in ``mapping`` must currently exist in either
      ``stdio.env`` or ``http.headers`` of the target server.
    - ``confirm_remove_raw`` must be exactly ``true`` (plan §6: "never
      auto-migrate"). The frontend's migration modal flips this only on
      the user's explicit click.

    Effects:
    - Adds ``mapping[env_key] -> credential_id`` to ``env_refs`` (stdio)
      or ``header_refs`` (http).
    - Removes the corresponding ``env_key`` from ``env`` / ``headers``.
    - Increments fingerprint via the standard update path (v2 includes
      env_refs / header_refs keys, M4).
    - Triggers reverse-index rebuild on the binding index.
    """
    from routers.credentials_router import get_credential_store
    from credential_bindings import get_credential_binding_index

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    mapping = body.get("mapping") or {}
    if not isinstance(mapping, dict) or not mapping:
        raise HTTPException(
            status_code=400,
            detail={"code": "mapping_required", "message": "non-empty mapping is required"},
        )
    if body.get("confirm_remove_raw") is not True:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "confirm_required",
                "message": "confirm_remove_raw must be true; raw values are never auto-migrated",
            },
        )

    store = get_mcp_server_store()
    try:
        config = store.get_internal(server_id)
    except McpServerNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"mcp server not found: {server_id}"
        ) from exc

    # Validate credentials exist + enabled.
    cred_store = get_credential_store()
    from credential_store import CredentialNotFoundError
    for env_key, cred_id in mapping.items():
        if not isinstance(env_key, str) or not env_key.strip():
            raise HTTPException(
                status_code=400,
                detail={"code": "mapping_key_invalid", "message": f"invalid env key: {env_key!r}"},
            )
        if not isinstance(cred_id, str) or not cred_id.strip():
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "mapping_value_invalid",
                    "message": f"invalid credential_id for {env_key!r}",
                },
            )
        try:
            cred = cred_store.get_internal(cred_id)
        except CredentialNotFoundError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "credential_not_found",
                    "message": f"credential {cred_id!r} bound to {env_key!r} not found",
                },
            ) from exc
        if not cred.enabled:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "credential_disabled",
                    "message": f"credential {cred_id!r} bound to {env_key!r} is disabled",
                },
            )

    # Apply migration to stdio.env or http.headers. We rebuild both blocks
    # and feed them through the standard update path so the approval state
    # machine + fingerprint v2 logic both fire normally.
    new_stdio: dict[str, Any] | None = None
    new_http: dict[str, Any] | None = None
    migrated_stdio: list[str] = []
    migrated_http: list[str] = []

    if config.stdio is not None:
        env = dict(config.stdio.env)
        env_refs = dict(config.stdio.env_refs)
        for env_key, cred_id in mapping.items():
            if env_key in env:
                env_refs[env_key] = cred_id
                del env[env_key]
                migrated_stdio.append(env_key)
        new_stdio = {
            "command": config.stdio.command,
            "args": list(config.stdio.args),
            "env": env,
            "env_refs": env_refs,
            "cwd_relative": config.stdio.cwd_relative,
        }
        # Preserve the optional absolute cwd field if present in the schema.
        if hasattr(config.stdio, "cwd") and getattr(config.stdio, "cwd", None) is not None:
            new_stdio["cwd"] = config.stdio.cwd
    if config.http is not None:
        headers = dict(config.http.headers)
        header_refs = dict(config.http.header_refs)
        for env_key, cred_id in mapping.items():
            if env_key in headers:
                header_refs[env_key] = cred_id
                del headers[env_key]
                migrated_http.append(env_key)
        new_http = {
            "url": config.http.url,
            "headers": headers,
            "header_refs": header_refs,
            "timeout_seconds": config.http.timeout_seconds,
        }

    if not migrated_stdio and not migrated_http:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "no_matching_env_keys",
                "message": "none of the supplied keys exist in this server's raw env / headers",
            },
        )

    public = store.update(
        server_id,
        McpServerConfigUpdate(stdio=new_stdio, http=new_http),
    )

    # Refresh derived state: catalog fingerprint changed → invalidate;
    # binding index needs rebuilt for the new env_refs. We rebuild via the
    # binding_index singleton (not installer._bindings) so tests that
    # inject a fresh index via set_credential_binding_index() see the
    # updated state.
    catalog = get_mcp_tool_catalog()
    catalog.invalidate(server_id)
    idx = get_credential_binding_index()
    idx.rebuild_from_mcp_store(store.list_internal())

    return {
        "server_id": server_id,
        "migrated_stdio_env_keys": migrated_stdio,
        "migrated_http_header_keys": migrated_http,
        "server": public.model_dump(mode="json"),
    }


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
