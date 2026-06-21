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
from enum import Enum
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
DEFAULT_MAX_TOOL_PAYLOAD_CHARS = 64_000
_FAILURE_MESSAGE_CHAR_LIMIT = 240
_CONTEXT_BUDGET_MESSAGE_LIMIT = 1600


class ToolLoopStopReason(str, Enum):
    """Machine-readable tool-loop stop reasons exposed beside legacy strings."""

    TOOL_LOOP_NOT_STARTED = "tool_loop_not_started"
    MCP_DISABLED_BY_POLICY = "mcp_disabled_by_policy"
    PROVIDER_TOOL_PROBE_FAILED = "provider_tool_probe_failed"
    TOOL_DISCOVERY_FAILED = "tool_discovery_failed"
    TOOLS_HIDDEN_BY_POLICY = "tools_hidden_by_policy"
    PROVIDER_NO_TOOL_CALLS = "provider_no_tool_calls"
    TOOL_LOOP_COMPLETED = "tool_loop_completed"
    TOOL_LOOP_MAX_ROUNDS = "tool_loop_max_rounds"
    TOOL_LOOP_TIMEOUT = "tool_loop_timeout"
    TOOL_LOOP_CANCELLED = "tool_loop_cancelled"
    ADAPTER_CONVERSION_ERROR = "adapter_conversion_error"
    CONTEXT_BUDGET_EXCEEDED = "context_budget_exceeded"
    TOOL_CALL_FAILED_NO_MODEL_PAYLOAD = "tool_call_failed_no_model_payload"


class ToolLoopTerminalState(str, Enum):
    """Run-level terminal bucket independent from assistant answer text."""

    NOT_STARTED = "not_started"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class ToolLoopEventType(str, Enum):
    """Stable event names for tool-loop projections and tests."""

    TOOL_LOOP_NOT_STARTED = "tool_loop_not_started"
    MCP_DISABLED_BY_POLICY = "mcp_disabled_by_policy"
    PROVIDER_TOOL_PROBE_FAILED = "provider_tool_probe_failed"
    TOOL_LOOP_STARTED = "tool_loop_started"
    TOOL_DISCOVERY_FAILED = "tool_discovery_failed"
    TOOLS_HIDDEN_BY_POLICY = "tools_hidden_by_policy"
    PROVIDER_NO_TOOL_CALLS = "provider_no_tool_calls"
    TOOL_CALL_RECEIVED = "tool_call_received"
    TOOL_CALL_DENIED = "tool_call_denied"
    TOOL_EXECUTION_ERROR_RETURNED = "tool_execution_error_returned"
    TOOL_CALL_FAILED_NO_MODEL_PAYLOAD = "tool_call_failed_no_model_payload"
    TOOL_RESULT_RENDERED = "tool_result_rendered"
    FOLLOW_UP_SENT = "follow_up_sent"
    TOOL_LOOP_COMPLETED = "tool_loop_completed"
    TOOL_LOOP_MAX_ROUNDS = "tool_loop_max_rounds"
    TOOL_LOOP_TIMEOUT = "tool_loop_timeout"
    TOOL_LOOP_CANCELLED = "tool_loop_cancelled"
    ADAPTER_CONVERSION_ERROR = "adapter_conversion_error"
    CONTEXT_BUDGET_EXCEEDED = "context_budget_exceeded"


@dataclass(frozen=True)
class ToolLoopEvent:
    """One bounded lifecycle event emitted by the provider tool loop.

    Args:
        event: Stable event name. Values are safe for UI reducers and tests.
        round_index: One-based provider round index when the event belongs to a round.
        tool_call_id: Provider tool call id when available.
        tool_name: Internal tool name when available.
        is_error: Tool-result error flag when the event represents a result.
        message: Short diagnostic text without secrets or raw provider payloads.
        metadata: Small JSON-safe counters or ids needed by projections.
    """

    event: ToolLoopEventType
    round_index: int | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    is_error: bool | None = None
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a compact JSON-safe event payload."""

        payload: dict[str, Any] = {"event": self.event.value}
        if self.round_index is not None:
            payload["round_index"] = self.round_index
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        if self.tool_name is not None:
            payload["tool_name"] = self.tool_name
        if self.is_error is not None:
            payload["is_error"] = self.is_error
        if self.message:
            payload["message"] = self.message
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class ToolLoopDiagnostics:
    """Typed run diagnostics for one bounded provider tool loop.

    Args:
        terminal_state: Coarse final state independent from answer text.
        stop_reason: Specific typed stop reason.
        legacy_stopped_reason: Backward-compatible runner string.
        rounds: Provider rounds attempted by the loop.
        offered_tool_count: Number of provider-facing tools in the first round.
        tool_call_count: Tool result records produced.
        tool_error_count: Tool result records marked as errors.
        tool_payloads_used: Number of provider-bound tool payloads produced.
        tool_payload_chars: Provider-bound tool payload chars actually sent.
        tool_payload_estimated_tokens: Character-derived token estimate.
        context_budget_chars: Configured total provider-bound tool payload budget.
        context_budget_remaining_chars: Remaining provider-bound budget at exit.
        context_budget_exceeded: Whether any payload was replaced by a budget summary.
        llm_payload_truncated_count: Provider-facing result payloads truncated.
        events: Ordered lifecycle events.
    """

    terminal_state: ToolLoopTerminalState
    stop_reason: ToolLoopStopReason
    legacy_stopped_reason: str
    rounds: int
    offered_tool_count: int
    tool_call_count: int
    tool_error_count: int
    tool_payloads_used: int
    tool_payload_chars: int
    tool_payload_estimated_tokens: int
    context_budget_chars: int
    context_budget_remaining_chars: int
    context_budget_exceeded: bool
    llm_payload_truncated_count: int
    events: list[ToolLoopEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return the public diagnostics shape used by API transcripts."""

        return {
            "terminal_state": self.terminal_state.value,
            "stop_reason": self.stop_reason.value,
            "legacy_stopped_reason": self.legacy_stopped_reason,
            "rounds": self.rounds,
            "offered_tool_count": self.offered_tool_count,
            "tool_call_count": self.tool_call_count,
            "tool_error_count": self.tool_error_count,
            "tool_payloads_used": self.tool_payloads_used,
            "tool_payload_chars": self.tool_payload_chars,
            "tool_payload_estimated_tokens": self.tool_payload_estimated_tokens,
            "context_budget_chars": self.context_budget_chars,
            "context_budget_remaining_chars": self.context_budget_remaining_chars,
            "context_budget_exceeded": self.context_budget_exceeded,
            "llm_payload_truncated_count": self.llm_payload_truncated_count,
            "events": [event.to_dict() for event in self.events],
        }


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
    max_tool_payload_chars: int = field(default_factory=lambda: _env_int("MCP_MAX_TOOL_PAYLOAD_CHARS", DEFAULT_MAX_TOOL_PAYLOAD_CHARS))

    def clamp_to_2x_defaults(self) -> "RunCaps":
        if os.environ.get("LITERATURE_MCP_RELAX_CAPS", "").strip() in {"1", "true", "yes", "on"}:
            return self
        return RunCaps(
            max_rounds=min(self.max_rounds, DEFAULT_MAX_ROUNDS * 2),
            max_total_seconds=min(self.max_total_seconds, DEFAULT_MAX_TOTAL_SECONDS * 2),
            max_parallel=min(self.max_parallel, DEFAULT_MAX_PARALLEL * 2),
            per_call_timeout=min(self.per_call_timeout, DEFAULT_PER_CALL_TIMEOUT * 2),
            max_tool_payload_chars=min(
                self.max_tool_payload_chars,
                DEFAULT_MAX_TOOL_PAYLOAD_CHARS * 2,
            ),
        )


@dataclass
class ToolUseRunResult:
    final_text: str
    final_response: dict[str, Any]
    rounds: int
    transcript: list[ToolResultRecord]
    stopped_reason: str  # "natural" | "max_rounds" | "max_seconds" | "no_tools"
    diagnostics: ToolLoopDiagnostics


# ChatCall(messages, tools) -> raw provider response dict
ChatCall = Callable[[list[dict[str, Any]], list[dict[str, Any]] | None], Awaitable[dict[str, Any]]]


def _safe_failure_message(exc: BaseException | str) -> str:
    """Return a short diagnostic string that avoids raw provider payloads."""

    if isinstance(exc, BaseException):
        text = f"{type(exc).__name__}: {exc}"
    else:
        text = str(exc)
    text = " ".join(text.split())
    if len(text) <= _FAILURE_MESSAGE_CHAR_LIMIT:
        return text
    return text[: _FAILURE_MESSAGE_CHAR_LIMIT - 1].rstrip() + "…"


def _estimate_tokens_from_chars(chars: int) -> int:
    """Return a deterministic token estimate for provider-bound diagnostics."""

    if chars <= 0:
        return 0
    return max(1, (chars + 3) // 4)


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


def _tool_error_event_type(record: ToolResultRecord) -> ToolLoopEventType:
    """Classify a tool error without exposing raw payload text."""

    lowered = record.preview.lower()
    if (
        "capability_blocked" in lowered
        or "user_rejected" in lowered
        or "pending_call_timeout" in lowered
        or "approval_blocked" in lowered
    ):
        return ToolLoopEventType.TOOL_CALL_DENIED
    return ToolLoopEventType.TOOL_EXECUTION_ERROR_RETURNED


def _terminal_state_for_stop_reason(
    stop_reason: ToolLoopStopReason,
) -> ToolLoopTerminalState:
    """Map a typed stop reason to a coarse terminal state."""

    if stop_reason in {
        ToolLoopStopReason.PROVIDER_NO_TOOL_CALLS,
        ToolLoopStopReason.TOOL_LOOP_COMPLETED,
    }:
        return ToolLoopTerminalState.COMPLETED
    if stop_reason in {
        ToolLoopStopReason.TOOLS_HIDDEN_BY_POLICY,
        ToolLoopStopReason.TOOL_LOOP_MAX_ROUNDS,
        ToolLoopStopReason.TOOL_LOOP_TIMEOUT,
        ToolLoopStopReason.TOOL_LOOP_CANCELLED,
        ToolLoopStopReason.CONTEXT_BUDGET_EXCEEDED,
    }:
        return ToolLoopTerminalState.STOPPED
    if stop_reason == ToolLoopStopReason.TOOL_LOOP_NOT_STARTED:
        return ToolLoopTerminalState.NOT_STARTED
    return ToolLoopTerminalState.FAILED


def _diagnostics_from_state(
    *,
    terminal_state: ToolLoopTerminalState | None,
    stop_reason: ToolLoopStopReason,
    legacy_stopped_reason: str,
    rounds: int,
    offered_tool_count: int,
    context_budget_chars: int = 0,
    context_budget_remaining_chars: int = 0,
    context_budget_exceeded: bool = False,
    transcript: list[ToolResultRecord],
    events: list[ToolLoopEvent],
) -> ToolLoopDiagnostics:
    """Build diagnostics from the runner's current bounded state."""

    if rounds < 0:
        raise ValueError("rounds must be non-negative")
    if offered_tool_count < 0:
        raise ValueError("offered_tool_count must be non-negative")
    if context_budget_chars < 0:
        raise ValueError("context_budget_chars must be non-negative")
    if context_budget_remaining_chars < 0:
        raise ValueError("context_budget_remaining_chars must be non-negative")
    payload_chars = sum(max(0, int(record.llm_payload_chars)) for record in transcript)

    return ToolLoopDiagnostics(
        terminal_state=terminal_state or _terminal_state_for_stop_reason(stop_reason),
        stop_reason=stop_reason,
        legacy_stopped_reason=legacy_stopped_reason,
        rounds=rounds,
        offered_tool_count=offered_tool_count,
        tool_call_count=len(transcript),
        tool_error_count=sum(1 for record in transcript if record.is_error),
        tool_payloads_used=sum(1 for record in transcript if record.llm_payload),
        tool_payload_chars=payload_chars,
        tool_payload_estimated_tokens=sum(
            max(0, int(record.estimated_tokens)) for record in transcript
        )
        or _estimate_tokens_from_chars(payload_chars),
        context_budget_chars=context_budget_chars,
        context_budget_remaining_chars=context_budget_remaining_chars,
        context_budget_exceeded=context_budget_exceeded,
        llm_payload_truncated_count=sum(
            1 for record in transcript if record.llm_payload_truncated
        ),
        events=events,
    )


def _context_budget_summary_payload(
    *,
    record: ToolResultRecord,
    budget_chars: int,
    used_chars: int,
    remaining_chars: int,
) -> str:
    """Return a model-visible summary when raw tool text cannot fit."""

    summary = {
        "tool_result_for_llm": {
            "tool_name": record.tool_name,
            "is_error": record.is_error,
            "context_budget_exceeded": True,
            "budget_chars": budget_chars,
            "used_chars_before_record": used_chars,
            "remaining_chars_before_record": remaining_chars,
            "payload_chars_omitted": record.llm_payload_chars,
            "estimated_tokens_omitted": record.estimated_tokens,
            "budget_class": record.budget_class,
            "source_provenance": record.source_provenance,
            "message": (
                "Tool result body was omitted because the run-level provider "
                "context budget for tool payloads was exhausted. Re-run with "
                "a narrower query, lower max_chars/top_k, or read a smaller ref."
            ),
        }
    }
    text = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    if len(text) <= _CONTEXT_BUDGET_MESSAGE_LIMIT:
        return text
    return text[: _CONTEXT_BUDGET_MESSAGE_LIMIT - 1].rstrip() + "…"


def _apply_context_budget_to_records(
    *,
    records: list[ToolResultRecord],
    budget_chars: int,
    used_chars: int,
) -> tuple[list[ToolResultRecord], int, bool]:
    """Apply a per-run provider-bound payload budget to new records."""

    if budget_chars < 0:
        raise ValueError("budget_chars must be non-negative")
    if used_chars < 0:
        raise ValueError("used_chars must be non-negative")
    if not records:
        return [], used_chars, False

    out: list[ToolResultRecord] = []
    exceeded = False
    for record in records:
        payload_chars = max(0, int(record.llm_payload_chars or len(record.llm_payload)))
        remaining = max(0, budget_chars - used_chars)
        if payload_chars <= remaining:
            out.append(record)
            used_chars += payload_chars
            continue
        exceeded = True
        summary_payload = _context_budget_summary_payload(
            record=record,
            budget_chars=budget_chars,
            used_chars=used_chars,
            remaining_chars=remaining,
        )
        budgeted = replace(
            record,
            llm_payload=summary_payload,
            llm_payload_truncated=True,
            llm_payload_chars=len(summary_payload),
            estimated_tokens=_estimate_tokens_from_chars(len(summary_payload)),
            budget_class="context_budget_exceeded",
        )
        out.append(budgeted)
        used_chars += len(summary_payload)
    return out, used_chars, exceeded


def _failure_response(
    *,
    error_type: str,
    message: str,
    provider_key: str,
    round_index: int,
) -> dict[str, Any]:
    """Return a provider-shaped local failure envelope for downstream parsers."""

    if not error_type.strip():
        raise ValueError("error_type must be non-empty")
    response: dict[str, Any] = {
        "error": {
            "type": error_type,
            "message": message,
            "provider_key": provider_key,
            "round_index": round_index,
        }
    }
    if provider_key == "claude":
        response["content"] = []
    return response


def failed_tool_use_run_result(
    *,
    stop_reason: ToolLoopStopReason,
    legacy_stopped_reason: str,
    message: str,
    provider: str = "",
    offered_tool_count: int = 0,
    metadata: dict[str, Any] | None = None,
) -> ToolUseRunResult:
    """Build a failed run result for policy gates outside the runner loop."""

    if stop_reason is ToolLoopStopReason.TOOL_LOOP_NOT_STARTED:
        terminal_state = ToolLoopTerminalState.NOT_STARTED
    else:
        terminal_state = ToolLoopTerminalState.FAILED
    event_type = ToolLoopEventType(stop_reason.value)
    provider_key = _provider_key(provider)
    event_metadata = dict(metadata or {})
    if provider:
        event_metadata.setdefault("provider_key", provider_key)
    safe_message = _safe_failure_message(message)
    events = [
        ToolLoopEvent(
            event=event_type,
            message=safe_message,
            metadata=event_metadata,
        )
    ]
    diagnostics = _diagnostics_from_state(
        terminal_state=terminal_state,
        stop_reason=stop_reason,
        legacy_stopped_reason=legacy_stopped_reason,
        rounds=0,
        offered_tool_count=max(0, int(offered_tool_count)),
        transcript=[],
        events=events,
    )
    return ToolUseRunResult(
        final_text="",
        final_response=_failure_response(
            error_type=stop_reason.value,
            message=safe_message,
            provider_key=provider_key,
            round_index=0,
        ),
        rounds=0,
        transcript=[],
        stopped_reason=legacy_stopped_reason,
        diagnostics=diagnostics,
    )


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

    @property
    def offered_tool_count(self) -> int:
        """Return provider-facing tool count for pre-run diagnostics.

        Why:
            Routers need this count for fail-closed provider-capability
            diagnostics before ``run()`` executes, without reading private
            catalog internals.
        """

        return sum(len(tools) for _config, tools in self._snapshot)

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
        events: list[ToolLoopEvent] = [
            ToolLoopEvent(
                event=ToolLoopEventType.TOOL_LOOP_STARTED,
                metadata={
                    "provider_key": provider_key,
                    "offered_tool_count": len(tools_payload),
                },
            )
        ]
        start = time.perf_counter()
        last_data: dict[str, Any] = {}
        rounds = 0
        stopped_reason = "natural"
        typed_stop_reason = ToolLoopStopReason.TOOL_LOOP_COMPLETED
        context_budget_chars = max(0, int(self._caps.max_tool_payload_chars))
        context_budget_used_chars = 0
        context_budget_exceeded = False
        # Reset remember-for-run cache at run() entry — D-MCPUX-4 forbids
        # cross-session persistence; the cache lives only for this run.
        self._remember_decisions = {}

        while rounds < self._caps.max_rounds:
            rounds += 1
            elapsed = time.perf_counter() - start
            if elapsed >= self._caps.max_total_seconds:
                stopped_reason = "max_seconds"
                typed_stop_reason = ToolLoopStopReason.TOOL_LOOP_TIMEOUT
                events.append(
                    ToolLoopEvent(
                        event=ToolLoopEventType.TOOL_LOOP_TIMEOUT,
                        round_index=rounds,
                        message="max_total_seconds elapsed before provider round",
                        metadata={"max_total_seconds": self._caps.max_total_seconds},
                    )
                )
                break

            try:
                data = await chat_call(messages, tools_payload if tools_payload else None)
            except Exception as exc:  # noqa: BLE001 - provider call errors become typed run diagnostics.
                message = _safe_failure_message(exc)
                stopped_reason = "provider_error"
                typed_stop_reason = ToolLoopStopReason.TOOL_CALL_FAILED_NO_MODEL_PAYLOAD
                events.append(
                    ToolLoopEvent(
                        event=ToolLoopEventType.TOOL_CALL_FAILED_NO_MODEL_PAYLOAD,
                        round_index=rounds,
                        message=message,
                        metadata={"provider_key": provider_key},
                    )
                )
                last_data = _failure_response(
                    error_type="provider_call_failed",
                    message=message,
                    provider_key=provider_key,
                    round_index=rounds,
                )
                break

            if not isinstance(data, dict):
                message = _safe_failure_message(
                    f"provider returned {type(data).__name__}, expected dict"
                )
                stopped_reason = "adapter_error"
                typed_stop_reason = ToolLoopStopReason.ADAPTER_CONVERSION_ERROR
                events.append(
                    ToolLoopEvent(
                        event=ToolLoopEventType.ADAPTER_CONVERSION_ERROR,
                        round_index=rounds,
                        message=message,
                        metadata={"provider_key": provider_key},
                    )
                )
                last_data = _failure_response(
                    error_type="adapter_conversion_error",
                    message=message,
                    provider_key=provider_key,
                    round_index=rounds,
                )
                break
            last_data = data
            try:
                calls = _extract_tool_calls_normalized(
                    data, provider_key, tool_name_aliases
                )
            except (AttributeError, KeyError, IndexError, TypeError, ValueError) as exc:
                message = _safe_failure_message(exc)
                stopped_reason = "adapter_error"
                typed_stop_reason = ToolLoopStopReason.ADAPTER_CONVERSION_ERROR
                events.append(
                    ToolLoopEvent(
                        event=ToolLoopEventType.ADAPTER_CONVERSION_ERROR,
                        round_index=rounds,
                        message=message,
                        metadata={"provider_key": provider_key},
                    )
                )
                last_data = _failure_response(
                    error_type="adapter_conversion_error",
                    message=message,
                    provider_key=provider_key,
                    round_index=rounds,
                )
                break

            if not calls:
                if not context_budget_exceeded:
                    stopped_reason = "no_tools" if rounds == 1 else "natural"
                    typed_stop_reason = (
                        ToolLoopStopReason.PROVIDER_NO_TOOL_CALLS
                        if rounds == 1
                        else ToolLoopStopReason.TOOL_LOOP_COMPLETED
                    )
                events.append(
                    ToolLoopEvent(
                        event=(
                            ToolLoopEventType.PROVIDER_NO_TOOL_CALLS
                            if rounds == 1
                            else ToolLoopEventType.TOOL_LOOP_COMPLETED
                        ),
                        round_index=rounds,
                        message=(
                            "provider returned no tool calls on first round"
                            if rounds == 1
                            else (
                                "provider returned final assistant message after context budget exhaustion"
                                if context_budget_exceeded
                                else "provider returned final assistant message"
                            )
                        ),
                        metadata={"offered_tool_count": len(tools_payload)},
                    )
                )
                break

            if context_budget_exceeded:
                stopped_reason = "context_budget_exceeded"
                typed_stop_reason = ToolLoopStopReason.CONTEXT_BUDGET_EXCEEDED
                events.append(
                    ToolLoopEvent(
                        event=ToolLoopEventType.CONTEXT_BUDGET_EXCEEDED,
                        round_index=rounds,
                        message=(
                            "provider requested more tools after the one-time "
                            "context budget summary was sent"
                        ),
                        metadata={
                            "requested_tool_count": len(calls),
                            "context_budget_chars": context_budget_chars,
                            "tool_payload_chars": context_budget_used_chars,
                        },
                    )
                )
                break

            # Append assistant message before tool results.
            messages.append(_build_assistant_message(data, provider_key))
            for call in calls:
                events.append(
                    ToolLoopEvent(
                        event=ToolLoopEventType.TOOL_CALL_RECEIVED,
                        round_index=rounds,
                        tool_call_id=call.tool_call_id,
                        tool_name=call.namespaced_name,
                    )
                )

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
            records, context_budget_used_chars, exceeded_now = _apply_context_budget_to_records(
                records=records,
                budget_chars=context_budget_chars,
                used_chars=context_budget_used_chars,
            )
            if exceeded_now:
                context_budget_exceeded = True
                stopped_reason = "context_budget_exceeded"
                typed_stop_reason = ToolLoopStopReason.CONTEXT_BUDGET_EXCEEDED
            transcript.extend(records)
            for record in records:
                events.append(
                    ToolLoopEvent(
                        event=(
                            _tool_error_event_type(record)
                            if record.is_error
                            else ToolLoopEventType.TOOL_RESULT_RENDERED
                        ),
                        round_index=rounds,
                        tool_call_id=record.tool_call_id,
                        tool_name=record.tool_name,
                        is_error=record.is_error,
                        metadata={
                            "elapsed_ms": record.elapsed_ms,
                            "llm_payload_truncated": record.llm_payload_truncated,
                            "llm_payload_chars": record.llm_payload_chars,
                            "estimated_tokens": record.estimated_tokens,
                            "budget_class": record.budget_class,
                        },
                    )
                )
                if record.budget_class == "context_budget_exceeded":
                    events.append(
                        ToolLoopEvent(
                            event=ToolLoopEventType.CONTEXT_BUDGET_EXCEEDED,
                            round_index=rounds,
                            tool_call_id=record.tool_call_id,
                            tool_name=record.tool_name,
                            message="run-level provider tool payload budget exhausted",
                            metadata={
                                "context_budget_chars": context_budget_chars,
                                "tool_payload_chars": context_budget_used_chars,
                                "omitted_source_provenance": dict(record.source_provenance),
                            },
                        )
                    )

            # Append tool result messages.
            messages.extend(_build_tool_result_messages(records, provider_key))
            events.append(
                ToolLoopEvent(
                    event=ToolLoopEventType.FOLLOW_UP_SENT,
                    round_index=rounds,
                    metadata={"tool_result_count": len(records)},
                )
            )
        else:
            # Loop exit via while condition (rounds == max_rounds).
            stopped_reason = "max_rounds"
            typed_stop_reason = ToolLoopStopReason.TOOL_LOOP_MAX_ROUNDS
            events.append(
                ToolLoopEvent(
                    event=ToolLoopEventType.TOOL_LOOP_MAX_ROUNDS,
                    round_index=rounds,
                    message="max_rounds reached while provider kept requesting tools",
                    metadata={"max_rounds": self._caps.max_rounds},
                )
            )

        final_text = _extract_final_text(last_data, provider_key)
        diagnostics = _diagnostics_from_state(
            terminal_state=None,
            stop_reason=typed_stop_reason,
            legacy_stopped_reason=stopped_reason,
            rounds=rounds,
            offered_tool_count=len(tools_payload),
            context_budget_chars=context_budget_chars,
            context_budget_remaining_chars=max(0, context_budget_chars - context_budget_used_chars),
            context_budget_exceeded=context_budget_exceeded,
            transcript=transcript,
            events=events,
        )
        return ToolUseRunResult(
            final_text=final_text,
            final_response=last_data,
            rounds=rounds,
            transcript=transcript,
            stopped_reason=stopped_reason,
            diagnostics=diagnostics,
        )


__all__ = [
    "ChatCall",
    "DEFAULT_MAX_PARALLEL",
    "DEFAULT_MAX_ROUNDS",
    "DEFAULT_MAX_TOTAL_SECONDS",
    "DEFAULT_PER_CALL_TIMEOUT",
    "McpToolUseRunner",
    "RunCaps",
    "ToolLoopDiagnostics",
    "ToolLoopEvent",
    "ToolLoopEventType",
    "ToolLoopStopReason",
    "ToolLoopTerminalState",
    "ToolUseRunResult",
    "failed_tool_use_run_result",
]
