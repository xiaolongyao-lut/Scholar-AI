"""Chat-side MCP integration helpers.

Lives next to chat_router so the router stays slim. Responsibilities:

  * Validate ``ChatRequest.mcp_server_ids`` against the runtime store.
  * Fetch the cached tool catalog for each enabled server.
  * Build the closure that the ``McpToolUseRunner`` calls every round.
  * Translate runner output (final text, transcript) into ChatResponse
    fields.

Behavior gate: this module is only invoked when
``LITERATURE_ENABLE_MCP_TOOLS`` is truthy AND the request supplies a
non-None ``mcp_server_ids`` (``[]`` is valid — audit-recorded zero-server
run).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable

from mcp_runtime.client_manager import get_mcp_client_manager
from mcp_runtime.server_store import McpServerNotFoundError
from mcp_runtime.tool_use_runner import (
    McpToolUseRunner,
    RunCaps,
    ToolUseRunResult,
)
from models.mcp import (
    McpApprovalState,
    McpServerConfig,
    McpToolDescriptor,
)
from routers import mcp_router as mcp_router_module
from routers.local_literature_tool_bridge import (
    LocalLiteratureToolUseRunner,
    local_literature_catalog,
    local_literature_catalog_snapshot,
    local_literature_server_config,
)


logger = logging.getLogger("ChatMcpIntegration")


def is_mcp_tools_enabled() -> bool:
    raw = os.environ.get("LITERATURE_ENABLE_MCP_TOOLS", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


class McpRequestValidationError(ValueError):
    """User-supplied mcp_server_ids reference a missing server."""


async def collect_enabled_servers_with_catalog(
    server_ids: list[str],
) -> tuple[list[McpServerConfig], list[tuple[McpServerConfig, list[McpToolDescriptor]]]]:
    """Look up requested servers + warm catalogs.

    Returns:
        servers: full list (including not-yet-enabled — dispatcher gates them)
        catalog_snapshot: only enabled_for_session servers contribute tool
          schemas; others are present in ``servers`` so reverse-lookup can
          still produce a "approval_blocked" record instead of a generic
          unknown-tool error.

    Raises:
        McpRequestValidationError: if any id is unknown.
    """
    store = mcp_router_module.get_mcp_server_store()
    catalog = mcp_router_module.get_mcp_tool_catalog()
    servers: list[McpServerConfig] = []
    snapshot: list[tuple[McpServerConfig, list[McpToolDescriptor]]] = []
    for sid in server_ids:
        try:
            cfg = store.get_internal(sid)
        except McpServerNotFoundError as exc:
            raise McpRequestValidationError(
                f"unknown mcp_server_id: {sid}"
            ) from exc
        servers.append(cfg)
        if cfg.approval_state != McpApprovalState.ENABLED_FOR_SESSION:
            continue
        try:
            tools = await catalog.get_tools(cfg)
        except Exception as exc:  # noqa: BLE001 — log + skip; runner reports
            logger.warning(
                "mcp_catalog_fetch_failed server=%s err=%s", sid, exc
            )
            continue
        snapshot.append((cfg, tools))
    return servers, snapshot


def make_runner(
    *,
    servers: list[McpServerConfig],
    catalog_snapshot: list[tuple[McpServerConfig, list[McpToolDescriptor]]],
    allow_high_risk_tools: bool,
    caps: RunCaps | None = None,
) -> McpToolUseRunner:
    return McpToolUseRunner(
        manager=get_mcp_client_manager(),
        catalog=mcp_router_module.get_mcp_tool_catalog(),
        servers=servers,
        catalog_snapshot=catalog_snapshot,
        caps=caps,
        allow_high_risk_tools=allow_high_risk_tools,
    )


def make_local_literature_runner(
    *,
    allow_high_risk_tools: bool,
    caps: RunCaps | None = None,
) -> LocalLiteratureToolUseRunner:
    """Return a runner exposing the built-in Literature Assistant tool surface."""

    config = local_literature_server_config()
    provider_runner = McpToolUseRunner(
        manager=get_mcp_client_manager(),
        catalog=local_literature_catalog(),
        servers=[config],
        catalog_snapshot=local_literature_catalog_snapshot(),
        caps=caps,
        allow_high_risk_tools=allow_high_risk_tools,
    )
    return LocalLiteratureToolUseRunner(
        provider_runner=provider_runner,
        allow_high_risk_tools=allow_high_risk_tools,
    )


# ChatPostFn(payload) -> raw provider response dict
ChatPostFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def make_chat_call(
    *,
    base_payload: dict[str, Any],
    provider_key: str,
    post_fn: ChatPostFn,
):
    """Return a runner-compatible ``chat_call(messages, tools)`` closure.

    Mutates a fresh copy of ``base_payload`` per round; never touches the
    caller's dict. For Claude, the ``system`` field stays put across rounds
    (it lives outside the messages array).
    """

    async def _chat_call(
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        payload = dict(base_payload)
        payload["messages"] = messages
        if tools:
            payload["tools"] = tools
        else:
            payload.pop("tools", None)
        # Streaming is forced off in tool loops — runner expects whole
        # response dicts.
        payload.pop("stream", None)
        return await post_fn(payload)

    return _chat_call


def transcript_to_dump(result: ToolUseRunResult) -> dict[str, Any]:
    """Compact JSON-ready dump of the run for ChatResponse / audit log."""
    return {
        "rounds": result.rounds,
        "stopped_reason": result.stopped_reason,
        "tool_calls": [
            {
                "tool_call_id": r.tool_call_id,
                "server_id": r.server_id,
                "server_slug": r.server_slug,
                "tool_name": r.tool_name,
                "is_error": r.is_error,
                "elapsed_ms": r.elapsed_ms,
                "preview": r.preview,
                "truncated": r.truncated,
            }
            for r in result.transcript
        ],
    }


__all__ = [
    "ChatPostFn",
    "McpRequestValidationError",
    "collect_enabled_servers_with_catalog",
    "is_mcp_tools_enabled",
    "make_chat_call",
    "make_local_literature_runner",
    "make_runner",
    "transcript_to_dump",
]
