"""MCP tool dispatcher (Phase 2 / TASK-203).

Routes one provider tool call to the right MCP server, enforces approval +
capability gates, invokes via the client manager, and returns an audit-
ready ``ToolResultRecord``. Never raises on tool-side errors — embeds them
so the LLM round trip can continue.

Approval gate (plan v0.3 §4.3):
  - Server must be in ``approval_state == enabled_for_session``.
  - Otherwise the dispatcher returns an error record with reason
    ``approval_blocked``; the LLM sees a tool_result with is_error=True.

Capability gate (plan v0.3 §4.5):
  - Tools tagged ``destructive``, ``write``, ``filesystem`` need a
    per-call elevation flag (``allow_high_risk_tools``). Phase 2 just
    enforces the flag; richer per-tool elevation lands in Phase 5.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from mcp_runtime.client_manager import (
    McpClientManager,
    McpClientManagerError,
    McpServerLaunchError,
    McpStreamableHttpDisabledError,
    McpToolCallError,
)
from mcp_runtime import audit as mcp_audit
from mcp_runtime.provider_tool_adapter import (
    NamespacedTool,
    ToolNamespaceError,
    parse_namespaced_tool,
)
from mcp_runtime.tool_catalog import McpToolCatalog
from mcp_runtime.tool_result_formatter import (
    ToolResultRecord,
    build_tool_result_record,
)
from models.mcp import (
    McpApprovalState,
    McpServerConfig,
    McpToolCapability,
    McpToolDescriptor,
)


logger = logging.getLogger("McpToolDispatcher")


_HIGH_RISK_CAPABILITIES = {
    McpToolCapability.WRITE,
    McpToolCapability.FILESYSTEM,
    McpToolCapability.DESTRUCTIVE,
}


@dataclass
class DispatchInput:
    """One provider tool call ready for dispatch.

    The chat router builds these from ``_extract_tool_calls`` output —
    Claude blocks and OpenAI tool_calls have different shapes; the
    runner normalizes them before handing to the dispatcher.
    """

    tool_call_id: str
    namespaced_name: str
    arguments: dict[str, Any]


def _normalize_arguments(arguments: Any) -> dict[str, Any]:
    """Provider tool calls may give arguments as dict or JSON string;
    normalize to dict.
    """
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        s = arguments.strip()
        if not s:
            return {}
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            return {"raw_arguments": s}
    return {"value": arguments}


def _error_record(
    *,
    tool_call_id: str,
    server_id: str,
    server_slug: str,
    tool_name: str,
    reason: str,
    elapsed_ms: int,
) -> ToolResultRecord:
    record = build_tool_result_record(
        tool_call_id=tool_call_id,
        server_id=server_id,
        server_slug=server_slug,
        tool_name=tool_name,
        raw={
            "is_error": True,
            "content": [{"type": "text", "text": reason}],
        },
        elapsed_ms=elapsed_ms,
    )
    mcp_audit.append(record)
    return record


class McpToolDispatcher:
    """Dispatches namespaced tool calls against a per-request server set."""

    def __init__(
        self,
        *,
        manager: McpClientManager,
        catalog: McpToolCatalog,
        servers: list[McpServerConfig],
        allow_high_risk_tools: bool = False,
    ) -> None:
        self._manager = manager
        self._catalog = catalog
        self._servers = {s.server_id: s for s in servers}
        self._slug_to_id = {s.server_slug: s.server_id for s in servers}
        self._allow_high_risk = allow_high_risk_tools

    @property
    def slug_to_server_id(self) -> dict[str, str]:
        return dict(self._slug_to_id)

    def _resolve(self, namespaced_name: str) -> NamespacedTool:
        return parse_namespaced_tool(
            namespaced_name, slug_to_server_id=self._slug_to_id
        )

    async def _find_descriptor(
        self, config: McpServerConfig, tool_name: str
    ) -> McpToolDescriptor | None:
        try:
            tools = await self._catalog.get_tools(config)
        except (McpServerLaunchError, McpClientManagerError):
            return None
        for t in tools:
            if t.name == tool_name:
                return t
        return None

    async def dispatch_one(self, call: DispatchInput) -> ToolResultRecord:
        start = time.perf_counter()
        # Resolve namespace → (server_id, tool_name)
        try:
            ns = self._resolve(call.namespaced_name)
        except ToolNamespaceError as exc:
            return _error_record(
                tool_call_id=call.tool_call_id,
                server_id="",
                server_slug="",
                tool_name=call.namespaced_name,
                reason=f"unknown_tool: {exc}",
                elapsed_ms=int((time.perf_counter() - start) * 1000),
            )

        config = self._servers.get(ns.server_id)
        if config is None:
            return _error_record(
                tool_call_id=call.tool_call_id,
                server_id=ns.server_id,
                server_slug=ns.server_slug,
                tool_name=ns.tool_name,
                reason=f"server_not_in_request_scope: {ns.server_id}",
                elapsed_ms=int((time.perf_counter() - start) * 1000),
            )

        # Approval gate.
        if config.approval_state != McpApprovalState.ENABLED_FOR_SESSION:
            return _error_record(
                tool_call_id=call.tool_call_id,
                server_id=ns.server_id,
                server_slug=ns.server_slug,
                tool_name=ns.tool_name,
                reason=(
                    f"approval_blocked: server {ns.server_slug} is "
                    f"{config.approval_state.value}, not enabled_for_session"
                ),
                elapsed_ms=int((time.perf_counter() - start) * 1000),
            )

        # Capability gate (best-effort: catalog may be cold).
        descriptor = await self._find_descriptor(config, ns.tool_name)
        if descriptor is None:
            return _error_record(
                tool_call_id=call.tool_call_id,
                server_id=ns.server_id,
                server_slug=ns.server_slug,
                tool_name=ns.tool_name,
                reason=f"unknown_tool_on_server: {ns.tool_name}",
                elapsed_ms=int((time.perf_counter() - start) * 1000),
            )

        if descriptor.capability in _HIGH_RISK_CAPABILITIES and not self._allow_high_risk:
            return _error_record(
                tool_call_id=call.tool_call_id,
                server_id=ns.server_id,
                server_slug=ns.server_slug,
                tool_name=ns.tool_name,
                reason=(
                    f"capability_blocked: tool {ns.tool_name} tagged "
                    f"{descriptor.capability.value}; require "
                    f"allow_high_risk_tools=true"
                ),
                elapsed_ms=int((time.perf_counter() - start) * 1000),
            )

        args = _normalize_arguments(call.arguments)
        try:
            raw = await self._manager.call_tool(config, ns.tool_name, args)
        except McpStreamableHttpDisabledError as exc:
            raw = {"is_error": True, "content": [{"type": "text", "text": str(exc)}]}
        except McpToolCallError as exc:
            raw = {
                "is_error": True,
                "content": [
                    {"type": "text", "text": f"tool_call_failed: {exc}"}
                ],
            }
        except (McpServerLaunchError, McpClientManagerError) as exc:
            raw = {
                "is_error": True,
                "content": [
                    {
                        "type": "text",
                        "text": f"server_unavailable: {type(exc).__name__}: {exc}",
                    }
                ],
            }

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        record = build_tool_result_record(
            tool_call_id=call.tool_call_id,
            server_id=ns.server_id,
            server_slug=ns.server_slug,
            tool_name=ns.tool_name,
            raw=raw,
            elapsed_ms=elapsed_ms,
        )
        mcp_audit.append(record)
        return record

    async def dispatch_many(
        self, calls: list[DispatchInput], *, max_parallel: int
    ) -> list[ToolResultRecord]:
        """Dispatch a batch of tool calls with a concurrency cap.

        Order in the returned list matches ``calls`` so the runner can pair
        each result back to its provider tool_call.
        """
        if not calls:
            return []
        if max_parallel <= 1:
            return [await self.dispatch_one(c) for c in calls]

        sem = asyncio.Semaphore(max_parallel)

        async def _bounded(call: DispatchInput) -> ToolResultRecord:
            async with sem:
                return await self.dispatch_one(call)

        return await asyncio.gather(*(_bounded(c) for c in calls))


__all__ = [
    "DispatchInput",
    "McpToolDispatcher",
]
