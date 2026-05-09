"""Bounded MCP tool-use loop (Phase 2 / TASK-204).

Drives the multi-round tool_use → tool_result → tool_use cycle between an
LLM provider and a set of MCP servers. The runner is provider-aware just
enough to assemble assistant + tool-result messages in the right shape;
all provider HTTP/auth lives in the chat_router via the ``chat_call``
callable handed in by the caller.

Caps (plan v0.3 §3.2 Q7 — conservative defaults):
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
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from mcp_runtime.client_manager import McpClientManager
from mcp_runtime.provider_tool_adapter import (
    build_provider_tools,
    build_slug_to_server_id,
)
from mcp_runtime.tool_catalog import McpToolCatalog
from mcp_runtime.tool_dispatcher import DispatchInput, McpToolDispatcher
from mcp_runtime.tool_result_formatter import (
    ToolResultRecord,
    format_for_claude,
    format_for_openai,
)
from models.mcp import McpServerConfig, McpToolDescriptor


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
    data: dict[str, Any], provider_key: str
) -> list[DispatchInput]:
    """Return a normalized list of DispatchInput; empty if none."""
    out: list[DispatchInput] = []
    if provider_key == "claude":
        for block in data.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                out.append(
                    DispatchInput(
                        tool_call_id=str(block.get("id", "")),
                        namespaced_name=str(block.get("name", "")),
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
        out.append(
            DispatchInput(
                tool_call_id=str(tc.get("id", "")),
                namespaced_name=str(fn.get("name", "")),
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
        )
        self._slug_to_id = build_slug_to_server_id(catalog_snapshot)

    @property
    def caps(self) -> RunCaps:
        return self._caps

    async def run(
        self,
        *,
        provider: str,
        initial_messages: list[dict[str, Any]],
        chat_call: ChatCall,
    ) -> ToolUseRunResult:
        provider_key = _provider_key(provider)
        tools_payload = build_provider_tools(provider, self._snapshot)
        messages = list(initial_messages)
        transcript: list[ToolResultRecord] = []
        start = time.perf_counter()
        last_data: dict[str, Any] = {}
        rounds = 0
        stopped_reason = "natural"

        while rounds < self._caps.max_rounds:
            rounds += 1
            elapsed = time.perf_counter() - start
            if elapsed >= self._caps.max_total_seconds:
                stopped_reason = "max_seconds"
                break

            data = await chat_call(messages, tools_payload if tools_payload else None)
            last_data = data
            calls = _extract_tool_calls_normalized(data, provider_key)

            if not calls:
                stopped_reason = "no_tools" if rounds == 1 else "natural"
                break

            # Append assistant message before tool results.
            messages.append(_build_assistant_message(data, provider_key))

            # Dispatch tool calls (parallel-capped).
            records = await self._dispatcher.dispatch_many(
                calls, max_parallel=self._caps.max_parallel
            )
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
