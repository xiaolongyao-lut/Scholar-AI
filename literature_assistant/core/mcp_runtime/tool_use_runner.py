"""Bounded MCP tool-use loop.

Drives the multi-round tool_use → tool_result → tool_use cycle between an
LLM provider and a set of MCP servers. The runner is provider-aware just
enough to assemble assistant + tool-result messages in the right shape;
all provider HTTP/auth lives in the chat_router via the ``chat_call``
callable handed in by the caller.

Caps:
  - MCP_MAX_TOOL_ROUNDS=4
  - MCP_MAX_TOTAL_TOOL_SECONDS=45
  - MCP_MAX_PARALLEL_TOOLS=2
  - MCP_TOOL_CALL_TIMEOUT_SECONDS=20

Per-request overrides may not exceed 2x defaults unless
LITERATURE_MCP_RELAX_CAPS=1.

Returned ``ToolUseRunResult`` carries the final assistant text, the
provider-format final response, and an ordered transcript of tool
records (audit-ready).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable

from mcp_runtime import audit as mcp_audit
from mcp_runtime.client_manager import McpClientManager
from mcp_runtime.pending_calls import (
    PENDING_CALL_TIMEOUT_SECONDS_DEFAULT,
    PendingCallStore,
    classify_action,
    get_pending_call_store,
)
from mcp_runtime.provider_tool_adapter import (
    NamespacedTool,
    ToolNamespaceError,
    build_provider_tool_name_map,
    build_provider_tools,
    build_slug_to_server_id,
    parse_namespaced_tool,
)
from mcp_runtime.tool_catalog import McpToolCatalog
from mcp_runtime.tool_dispatcher import DispatchInput, McpToolDispatcher
from mcp_runtime.tool_result_formatter import (
    ToolResultRecord,
    build_tool_result_record,
    format_for_claude,
    format_for_openai,
)
from models.mcp import (
    McpServerConfig,
    McpToolCapability,
    McpToolDescriptor,
    PendingMcpToolCall,
)


logger = logging.getLogger("McpToolUseRunner")


DEFAULT_MAX_ROUNDS = 4
DEFAULT_MAX_TOTAL_SECONDS = 45.0
DEFAULT_MAX_PARALLEL = 2
DEFAULT_PER_CALL_TIMEOUT = 20.0


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return max(0.1, float(raw))
    except ValueError:
        return default


@dataclass
class RunCaps:
    max_rounds: int = field(default_factory=lambda: _env_int("MCP_MAX_TOOL_ROUNDS", DEFAULT_MAX_ROUNDS))
    max_total_seconds: float = field(default_factory=lambda: _env_float("MCP_MAX_TOTAL_TOOL_SECONDS", DEFAULT_MAX_TOTAL_SECONDS))
    max_parallel: int = field(default_factory=lambda: _env_int("MCP_MAX_PARALLEL_TOOLS", DEFAULT_MAX_PARALLEL))
    per_call_timeout: float = field(default_factory=lambda: _env_float("MCP_TOOL_CALL_TIMEOUT_SECONDS", DEFAULT_PER_CALL_TIMEOUT))

    def clamp_to_2x_defaults(self) -> "RunCaps":
        if os.environ.get("LITERATURE_MCP_RELAX_CAPS", "").strip() in {"1", "true", "yes", "on"}:
            return self
        return RunCaps(
            max_rounds=min(self.max_rounds, DEFAULT_MAX_ROUNDS * 2),
            max_total_seconds=min(self.max_total_seconds, DEFAULT_MAX_TOTAL_SECONDS * 2),
            max_parallel=min(self.max_parallel, DEFAULT_MAX_PARALLEL * 2),
            per_call_timeout=min(self.per_call_timeout, DEFAULT_PER_CALL_TIMEOUT * 2),
        )


@dataclass
class ToolUseRunResult:
    final_text: str
    final_response: dict[str, Any]
    rounds: int
    transcript: list[ToolResultRecord]
    stopped_reason: str  # "natural" | "max_rounds" | "max_seconds" | "no_tools"


# ChatCall(messages, tools) -> raw provider response dict
ChatCall = Callable[[list[dict[str, Any]], list[dict[str, Any]] | None], Awaitable[dict[str, Any]]]


def _provider_key(provider: str) -> str:
    p = (provider or "").strip().lower()
    return "claude" if p in {"claude", "anthropic"} else "openai"


# ---------------------------------------------------------------------------
# Provider-specific extraction
# ---------------------------------------------------------------------------


def _extract_tool_calls_normalized(
    data: dict[str, Any], provider_key: str, tool_name_aliases: dict[str, str] | None = None
) -> list[DispatchInput]:
    """Return a normalized list of DispatchInput; empty if none."""
    aliases = tool_name_aliases or {}
    out: list[DispatchInput] = []
    if provider_key == "claude":
        for block in data.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                provider_name = str(block.get("name", ""))
                out.append(
                    DispatchInput(
                        tool_call_id=str(block.get("id", "")),
                        namespaced_name=aliases.get(provider_name, provider_name),
                        arguments=block.get("input", {}) or {},
                    )
                )
        return out

    # OpenAI-compatible
    msg = (data.get("choices") or [{}])[0].get("message", {}) or {}
    for tc in msg.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        provider_name = str(fn.get("name", ""))
        out.append(
            DispatchInput(
                tool_call_id=str(tc.get("id", "")),
                namespaced_name=aliases.get(provider_name, provider_name),
                arguments=fn.get("arguments", {}),
            )
        )
    return out


def _extract_final_text(data: dict[str, Any], provider_key: str) -> str:
    if provider_key == "claude":
        parts = []
        for block in data.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    msg = (data.get("choices") or [{}])[0].get("message", {}) or {}
    content = msg.get("content")
    if isinstance(content, list):
        return "".join(
            str(p.get("text", ""))
            for p in content
            if isinstance(p, dict) and p.get("type") in {"text", "output_text"}
        )
    return str(content or "")


# ---------------------------------------------------------------------------
# Provider-specific message append
# ---------------------------------------------------------------------------


def _build_assistant_message(
    data: dict[str, Any], provider_key: str
) -> dict[str, Any]:
    """Build the assistant message to append to history before tool results."""
    if provider_key == "claude":
        return {
            "role": "assistant",
            "content": data.get("content", []) or [],
        }
    msg = (data.get("choices") or [{}])[0].get("message", {}) or {}
    return {
        "role": "assistant",
        "content": msg.get("content"),
        "tool_calls": msg.get("tool_calls") or [],
    }


def _build_tool_result_messages(
    records: list[ToolResultRecord], provider_key: str
) -> list[dict[str, Any]]:
    """Convert dispatch records into the next-round provider messages."""
    if provider_key == "claude":
        # Claude expects ONE user message containing all tool_result blocks.
        return [{
            "role": "user",
            "content": [format_for_claude(r) for r in records],
        }]
    # OpenAI: each tool result is its own role=tool message.
    return [format_for_openai(r) for r in records]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class McpToolUseRunner:
    """Provider-agnostic bounded tool-use loop.

    Caller responsibilities:
      - Build the *initial* messages array (system + history + user query).
      - Provide ``chat_call(messages, tools)`` that returns the raw provider
        response dict.
      - Provide the catalog (cfg, list[tool]) for the requested servers,
        already gated on approval state.
    """

    def __init__(
        self,
        *,
        manager: McpClientManager,
        catalog: McpToolCatalog,
        servers: list[McpServerConfig],
        catalog_snapshot: list[tuple[McpServerConfig, list[McpToolDescriptor]]],
        caps: RunCaps | None = None,
        allow_high_risk_tools: bool = False,
        pending_call_resolver: Any | None = None,
        pending_call_store: PendingCallStore | None = None,
    ) -> None:
        self._manager = manager
        self._catalog = catalog
        self._servers = servers
        self._snapshot = catalog_snapshot
        self._caps = (caps or RunCaps()).clamp_to_2x_defaults()
        self._dispatcher = McpToolDispatcher(
            manager=manager,
            catalog=catalog,
            servers=servers,
            allow_high_risk_tools=allow_high_risk_tools,
            per_call_timeout=(caps or RunCaps()).per_call_timeout,
        )
        self._allow_high_risk_tools = bool(allow_high_risk_tools)
        self._slug_to_id = build_slug_to_server_id(catalog_snapshot)
        # Pending-call protocol resolver. None preserves the immediate-dispatch
        # path; non-None enables ask flow. When None, ask-classified tools
        # auto-reject (safe default).
        self._pending_call_resolver = pending_call_resolver
        self._pending_call_store = pending_call_store or get_pending_call_store()
        # Per-run remember_for_run cache. Cleared at run() entry.
        # Key: (server_id, tool_name). Value: "approve" | "reject".
        self._remember_decisions: dict[tuple[str, str], str] = {}

    @property
    def caps(self) -> RunCaps:
        return self._caps

    # ---------------------------------------------------------------- gating

    def _lookup_capability(self, namespaced_name: str) -> tuple[NamespacedTool | None, McpToolCapability | None]:
        """Resolve (NamespacedTool, capability) from the catalog snapshot.
        Returns (ns, capability) where either field may be None when the
        lookup misses — the dispatcher then produces the right error
        record for the user-visible report.
        """
        try:
            ns = parse_namespaced_tool(namespaced_name, slug_to_server_id=self._slug_to_id)
        except ToolNamespaceError:
            return None, None
        for cfg, tools in self._snapshot:
            if cfg.server_id == ns.server_id:
                for tool in tools:
                    if tool.name == ns.tool_name:
                        return ns, tool.capability
                return ns, None
        return ns, None

    def _short_circuit_record(
        self,
        *,
        call: DispatchInput,
        ns: NamespacedTool | None,
        reason: str,
    ) -> ToolResultRecord:
        return build_tool_result_record(
            tool_call_id=call.tool_call_id,
            server_id=ns.server_id if ns else "",
            server_slug=ns.server_slug if ns else "",
            tool_name=ns.tool_name if ns else call.namespaced_name,
            raw={"is_error": True, "content": [{"type": "text", "text": reason}]},
            elapsed_ms=0,
        )

    @staticmethod
    def _args_preview(arguments: Any) -> str:
        try:
            text = json.dumps(arguments, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(arguments)
        return text[:512]

    async def _await_decision(
        self, pending: PendingMcpToolCall
    ) -> dict[str, Any]:
        """Await the operator decision via the configured resolver.

        Respects RunCaps.per_call_timeout. The same cap that bounds tool execution also bounds the
        human-in-the-loop wait — both protect the chat round trip).
        Raises asyncio.TimeoutError on cap breach.

        If no resolver is configured, returns a safe-default reject
        immediately (preserves "no UI → no accidental approval").
        """
        if self._pending_call_resolver is None:
            return {"decision": "reject", "remember_for_run": False, "reason": "no_resolver"}
        timeout = max(0.001, float(self._caps.per_call_timeout))
        result = await asyncio.wait_for(
            self._pending_call_resolver(pending),
            timeout=timeout,
        )
        if not isinstance(result, dict) or "decision" not in result:
            raise RuntimeError(
                f"pending_call_resolver returned malformed result: {result!r}"
            )
        return result

    async def _gate_calls(
        self, calls: list[DispatchInput]
    ) -> tuple[list[DispatchInput], dict[str, ToolResultRecord]]:
        """Apply the pending-call protocol to every call in this round.

        For each call we look up its capability, run classify_action,
        then route to allow / ask / block. Short-circuit records (block,
        rejected, timeout, malformed) bypass the dispatcher entirely and
        carry their own audit write here. Ask-approved calls receive
        ``allow_high_risk=True`` so the dispatcher's capability gate
        passes.

        Returns (calls_to_dispatch_in_original_order, short_circuit_records_by_id).
        """
        to_dispatch: list[DispatchInput] = []
        short_circuits: dict[str, ToolResultRecord] = {}

        for call in calls:
            ns, capability = self._lookup_capability(call.namespaced_name)
            if capability is None:
                # Catalog miss — let the dispatcher produce its standard
                # unknown_tool / unknown_tool_on_server error record.
                to_dispatch.append(call)
                continue

            action = classify_action(capability)
            if action == "allow":
                to_dispatch.append(call)
                continue

            if action == "block":
                reason = (
                    f"capability_blocked: tool {ns.tool_name if ns else call.namespaced_name} "
                    f"tagged destructive; blocked by pending-call protocol"
                )
                record = self._short_circuit_record(call=call, ns=ns, reason=reason)
                mcp_audit.append(record, decision="blocked", decision_user="policy")
                short_circuits[call.tool_call_id] = record
                continue

            # action == "ask"
            if self._allow_high_risk_tools:
                to_dispatch.append(replace(call, allow_high_risk=True))
                continue

            cache_key = (ns.server_id if ns else "", ns.tool_name if ns else call.namespaced_name)
            cached = self._remember_decisions.get(cache_key)
            if cached == "approve":
                to_dispatch.append(replace(call, allow_high_risk=True))
                continue
            if cached == "reject":
                record = self._short_circuit_record(
                    call=call, ns=ns,
                    reason="user_rejected: cached reject decision for this run",
                )
                mcp_audit.append(record, decision="rejected", decision_user="operator")
                short_circuits[call.tool_call_id] = record
                continue

            # No cached decision: emit PendingMcpToolCall and await resolver.
            pending = self._pending_call_store.create(
                server_id=ns.server_id if ns else "",
                tool_name=ns.tool_name if ns else call.namespaced_name,
                capability=capability,
                args_preview=self._args_preview(call.arguments),
            )
            try:
                decision = await self._await_decision(pending)
            except asyncio.TimeoutError:
                # Remove the still-pending entry so the store doesn't leak.
                try:
                    self._pending_call_store.decide(
                        pending.id, decision="reject", decision_user="timeout"
                    )
                except KeyError:
                    pass
                record = self._short_circuit_record(
                    call=call, ns=ns,
                    reason="pending_call_timeout: no operator decision within per_call_timeout",
                )
                mcp_audit.append(record, decision="timeout", decision_user="system")
                short_circuits[call.tool_call_id] = record
                continue

            # Normal decision path: remove the pending entry (resolver may
            # already have called decide(), in which case KeyError is OK).
            try:
                self._pending_call_store.decide(
                    pending.id,
                    decision=decision.get("decision", "reject"),
                    remember_for_run=bool(decision.get("remember_for_run", False)),
                    decision_user=decision.get("decision_user", "operator"),
                )
            except KeyError:
                pass

            if bool(decision.get("remember_for_run", False)):
                self._remember_decisions[cache_key] = decision["decision"]

            if decision["decision"] == "approve":
                to_dispatch.append(replace(call, allow_high_risk=True))
            else:
                record = self._short_circuit_record(
                    call=call, ns=ns,
                    reason=(
                        f"user_rejected: operator declined "
                        f"{ns.tool_name if ns else call.namespaced_name}"
                    ),
                )
                mcp_audit.append(
                    record,
                    decision="rejected",
                    decision_user=decision.get("decision_user", "operator"),
                )
                short_circuits[call.tool_call_id] = record

        return to_dispatch, short_circuits

    async def run(
        self,
        *,
        provider: str,
        initial_messages: list[dict[str, Any]],
        chat_call: ChatCall,
    ) -> ToolUseRunResult:
        provider_key = _provider_key(provider)
        tools_payload = build_provider_tools(provider, self._snapshot)
        tool_name_aliases = build_provider_tool_name_map(self._snapshot)
        messages = list(initial_messages)
        transcript: list[ToolResultRecord] = []
        start = time.perf_counter()
        last_data: dict[str, Any] = {}
        rounds = 0
        stopped_reason = "natural"
        # Reset remember-for-run cache at run() entry — D-MCPUX-4 forbids
        # cross-session persistence; the cache lives only for this run.
        self._remember_decisions = {}

        while rounds < self._caps.max_rounds:
            rounds += 1
            elapsed = time.perf_counter() - start
            if elapsed >= self._caps.max_total_seconds:
                stopped_reason = "max_seconds"
                break

            data = await chat_call(messages, tools_payload if tools_payload else None)
            last_data = data
            calls = _extract_tool_calls_normalized(data, provider_key, tool_name_aliases)

            if not calls:
                stopped_reason = "no_tools" if rounds == 1 else "natural"
                break

            # Append assistant message before tool results.
            messages.append(_build_assistant_message(data, provider_key))

            # Pending-call gate before dispatch.
            to_dispatch, short_circuits = await self._gate_calls(calls)
            dispatched = await self._dispatcher.dispatch_many(
                to_dispatch, max_parallel=self._caps.max_parallel
            )
            dispatched_by_id = {r.tool_call_id: r for r in dispatched}

            # Merge in original call order so the LLM gets results paired
            # to each tool_call_id.
            records = [
                short_circuits.get(c.tool_call_id) or dispatched_by_id[c.tool_call_id]
                for c in calls
            ]
            transcript.extend(records)

            # Append tool result messages.
            messages.extend(_build_tool_result_messages(records, provider_key))
        else:
            # Loop exit via while condition (rounds == max_rounds).
            stopped_reason = "max_rounds"

        final_text = _extract_final_text(last_data, provider_key)
        return ToolUseRunResult(
            final_text=final_text,
            final_response=last_data,
            rounds=rounds,
            transcript=transcript,
            stopped_reason=stopped_reason,
        )


__all__ = [
    "ChatCall",
    "DEFAULT_MAX_PARALLEL",
    "DEFAULT_MAX_ROUNDS",
    "DEFAULT_MAX_TOTAL_SECONDS",
    "DEFAULT_PER_CALL_TIMEOUT",
    "McpToolUseRunner",
    "RunCaps",
    "ToolUseRunResult",
]
