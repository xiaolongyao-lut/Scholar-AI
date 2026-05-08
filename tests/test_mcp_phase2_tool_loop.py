"""Phase 2 unit tests: provider_tool_adapter, tool_result_formatter,
tool_dispatcher, tool_use_runner, chat_mcp_integration.

Pure-Python (no MCP SDK required for the dispatcher / runner / formatter
suites — they use a fake manager). The chat integration smoke spins up a
TestClient with a fake LLM endpoint and the Phase 0 echo_math fixture
behind the per-operation MCP session manager; that one is gated on the
real ``mcp`` SDK being importable.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from mcp_runtime.provider_tool_adapter import (
    NAMESPACE_PREFIX,
    NamespacedTool,
    ToolNamespaceError,
    build_provider_tools,
    build_slug_to_server_id,
    namespace_tool_name,
    parse_namespaced_tool,
)
from mcp_runtime.tool_dispatcher import DispatchInput, McpToolDispatcher
from mcp_runtime.tool_result_formatter import (
    PREVIEW_CHAR_LIMIT,
    ToolResultRecord,
    build_tool_result_record,
    format_for_claude,
    format_for_openai,
    format_for_provider,
    format_generic_xml,
)
from mcp_runtime.tool_use_runner import (
    DEFAULT_MAX_PARALLEL,
    DEFAULT_MAX_ROUNDS,
    McpToolUseRunner,
    RunCaps,
)
from models.mcp import (
    McpApprovalState,
    McpProvenance,
    McpServerConfig,
    McpStdioConfig,
    McpToolCapability,
    McpToolDescriptor,
    McpTransport,
)


# ---------------------------------------------------------------------------
# Fixtures: minimal McpServerConfig + descriptors
# ---------------------------------------------------------------------------


def _server(
    *,
    server_id: str = "mcp_demo",
    slug: str = "demo",
    state: McpApprovalState = McpApprovalState.ENABLED_FOR_SESSION,
) -> McpServerConfig:
    now = "2026-05-09T00:00:00+00:00"
    return McpServerConfig(
        name="Demo",
        server_slug=slug,
        transport=McpTransport.STDIO,
        stdio=McpStdioConfig(command="python", args=["-m", "noop"]),
        provenance=McpProvenance.RUNTIME_USER_CONFIRMED,
        server_id=server_id,
        approval_state=state,
        fingerprint="abc123",
        created_at=now,
        updated_at=now,
    )


def _tool(name: str = "echo", capability: McpToolCapability = McpToolCapability.READ) -> McpToolDescriptor:
    return McpToolDescriptor(
        name=name,
        description=f"echoes {name}",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        capability=capability,
    )


# ---------------------------------------------------------------------------
# provider_tool_adapter
# ---------------------------------------------------------------------------


def test_namespace_round_trip() -> None:
    cfg = _server(slug="srv-a")
    name = namespace_tool_name("srv-a", "echo")
    assert name == "mcp__srv-a__echo"
    parsed = parse_namespaced_tool(
        name, slug_to_server_id={"srv-a": cfg.server_id}
    )
    assert parsed == NamespacedTool(server_id=cfg.server_id, server_slug="srv-a", tool_name="echo")


def test_namespace_rejects_missing_prefix() -> None:
    with pytest.raises(ToolNamespaceError, match="missing"):
        parse_namespaced_tool("plain_tool", slug_to_server_id={})


def test_namespace_rejects_unknown_slug() -> None:
    with pytest.raises(ToolNamespaceError, match="unknown server_slug"):
        parse_namespaced_tool("mcp__unknown__echo", slug_to_server_id={})


def test_namespace_rejects_malformed() -> None:
    with pytest.raises(ToolNamespaceError):
        parse_namespaced_tool("mcp__justslug__", slug_to_server_id={"justslug": "x"})


def test_build_provider_tools_claude_shape() -> None:
    cfg = _server(slug="srv")
    tools = build_provider_tools("Claude", [(cfg, [_tool("echo"), _tool("add")])])
    assert len(tools) == 2
    assert tools[0]["name"] == "mcp__srv__echo"
    assert "input_schema" in tools[0]
    assert "type" not in tools[0]  # Claude shape, not OpenAI


def test_build_provider_tools_openai_shape() -> None:
    cfg = _server(slug="srv")
    tools = build_provider_tools("DeepSeek", [(cfg, [_tool("echo")])])
    assert len(tools) == 1
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "mcp__srv__echo"
    assert "parameters" in tools[0]["function"]


def test_build_slug_to_server_id_helper() -> None:
    a = _server(server_id="mcp_a", slug="a")
    b = _server(server_id="mcp_b", slug="b")
    m = build_slug_to_server_id([(a, []), (b, [])])
    assert m == {"a": "mcp_a", "b": "mcp_b"}


# ---------------------------------------------------------------------------
# tool_result_formatter
# ---------------------------------------------------------------------------


def _record(
    *,
    is_error: bool = False,
    text: str = "hello",
) -> ToolResultRecord:
    return build_tool_result_record(
        tool_call_id="call_1",
        server_id="mcp_demo",
        server_slug="demo",
        tool_name="echo",
        raw={"is_error": is_error, "content": [{"type": "text", "text": text}]},
        elapsed_ms=12,
    )


def test_record_truncates_long_preview() -> None:
    big = "x" * (PREVIEW_CHAR_LIMIT + 200)
    rec = _record(text=big)
    assert rec.truncated is True
    assert rec.preview.endswith("...[truncated]")


def test_record_redacts_bearer_token_in_preview() -> None:
    rec = _record(text="Authorization: Bearer abcdefghij1234567890")
    assert "abcdefghij1234567890" not in rec.preview


def test_format_for_claude_block_shape() -> None:
    rec = _record(text="ok")
    block = format_for_claude(rec)
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "call_1"
    assert block["content"][0]["text"] == "ok"


def test_format_for_openai_message_shape() -> None:
    rec = _record(text="ok")
    msg = format_for_openai(rec)
    assert msg["role"] == "tool"
    assert msg["tool_call_id"] == "call_1"
    assert msg["content"] == "ok"


def test_format_generic_xml_includes_metadata() -> None:
    rec = _record(text="ok", is_error=True)
    xml = format_generic_xml(rec)
    assert "tool=\"echo\"" in xml
    assert "is_error=\"true\"" in xml
    assert "ok" in xml


def test_format_for_provider_dispatch() -> None:
    rec = _record(text="ok")
    assert format_for_provider("claude", rec)["type"] == "tool_result"
    assert format_for_provider("openai", rec)["role"] == "tool"
    assert "<tool_result" in format_for_provider("gemini-noop", rec)


# ---------------------------------------------------------------------------
# tool_dispatcher (with fake manager + catalog)
# ---------------------------------------------------------------------------


@dataclass
class _FakeManager:
    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    response: dict[str, Any] = field(default_factory=lambda: {"is_error": False, "content": [{"type": "text", "text": "ok"}]})

    async def call_tool(self, config, tool_name, arguments):
        self.calls.append((config.server_id, tool_name, arguments))
        return self.response


@dataclass
class _FakeCatalog:
    tools: list[McpToolDescriptor] = field(default_factory=list)

    async def get_tools(self, config, *, refresh: bool = False):
        return list(self.tools)


@pytest.mark.asyncio
async def test_dispatch_success_returns_record() -> None:
    cfg = _server()
    cat = _FakeCatalog(tools=[_tool("echo")])
    mgr = _FakeManager()
    disp = McpToolDispatcher(manager=mgr, catalog=cat, servers=[cfg])
    rec = await disp.dispatch_one(DispatchInput(
        tool_call_id="call_1",
        namespaced_name="mcp__demo__echo",
        arguments={"text": "hi"},
    ))
    assert rec.is_error is False
    assert rec.tool_name == "echo"
    assert rec.preview == "ok"
    assert mgr.calls == [(cfg.server_id, "echo", {"text": "hi"})]


@pytest.mark.asyncio
async def test_dispatch_blocks_when_not_enabled_for_session() -> None:
    cfg = _server(state=McpApprovalState.CATALOG_REVIEWED)
    disp = McpToolDispatcher(
        manager=_FakeManager(), catalog=_FakeCatalog(tools=[_tool("echo")]), servers=[cfg],
    )
    rec = await disp.dispatch_one(DispatchInput(
        tool_call_id="c", namespaced_name="mcp__demo__echo", arguments={},
    ))
    assert rec.is_error is True
    assert "approval_blocked" in rec.preview


@pytest.mark.asyncio
async def test_dispatch_blocks_high_risk_without_elevation() -> None:
    cfg = _server()
    disp = McpToolDispatcher(
        manager=_FakeManager(),
        catalog=_FakeCatalog(tools=[_tool("rm", capability=McpToolCapability.DESTRUCTIVE)]),
        servers=[cfg],
    )
    rec = await disp.dispatch_one(DispatchInput(
        tool_call_id="c", namespaced_name="mcp__demo__rm", arguments={},
    ))
    assert rec.is_error is True
    assert "capability_blocked" in rec.preview


@pytest.mark.asyncio
async def test_dispatch_allows_high_risk_when_elevated() -> None:
    cfg = _server()
    disp = McpToolDispatcher(
        manager=_FakeManager(),
        catalog=_FakeCatalog(tools=[_tool("rm", capability=McpToolCapability.WRITE)]),
        servers=[cfg],
        allow_high_risk_tools=True,
    )
    rec = await disp.dispatch_one(DispatchInput(
        tool_call_id="c", namespaced_name="mcp__demo__rm", arguments={},
    ))
    assert rec.is_error is False


@pytest.mark.asyncio
async def test_dispatch_unknown_namespace() -> None:
    cfg = _server()
    disp = McpToolDispatcher(manager=_FakeManager(), catalog=_FakeCatalog(), servers=[cfg])
    rec = await disp.dispatch_one(DispatchInput(
        tool_call_id="c", namespaced_name="bogus_name", arguments={},
    ))
    assert rec.is_error is True
    assert "unknown_tool" in rec.preview


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_on_known_server() -> None:
    cfg = _server()
    disp = McpToolDispatcher(
        manager=_FakeManager(), catalog=_FakeCatalog(tools=[_tool("echo")]), servers=[cfg]
    )
    rec = await disp.dispatch_one(DispatchInput(
        tool_call_id="c", namespaced_name="mcp__demo__not_here", arguments={},
    ))
    assert rec.is_error is True
    assert "unknown_tool_on_server" in rec.preview


@pytest.mark.asyncio
async def test_dispatch_normalizes_string_arguments() -> None:
    cfg = _server()
    mgr = _FakeManager()
    disp = McpToolDispatcher(manager=mgr, catalog=_FakeCatalog(tools=[_tool("echo")]), servers=[cfg])
    await disp.dispatch_one(DispatchInput(
        tool_call_id="c", namespaced_name="mcp__demo__echo", arguments='{"text": "hi"}',
    ))
    assert mgr.calls == [(cfg.server_id, "echo", {"text": "hi"})]


@pytest.mark.asyncio
async def test_dispatch_many_preserves_order() -> None:
    cfg = _server()
    mgr = _FakeManager()
    disp = McpToolDispatcher(manager=mgr, catalog=_FakeCatalog(tools=[_tool("echo")]), servers=[cfg])
    calls = [
        DispatchInput(tool_call_id=f"c{i}", namespaced_name="mcp__demo__echo", arguments={"i": i})
        for i in range(3)
    ]
    out = await disp.dispatch_many(calls, max_parallel=2)
    assert [r.tool_call_id for r in out] == ["c0", "c1", "c2"]


# ---------------------------------------------------------------------------
# tool_use_runner
# ---------------------------------------------------------------------------


def test_run_caps_clamp_to_2x_defaults() -> None:
    caps = RunCaps(max_rounds=99, max_total_seconds=999.0, max_parallel=99, per_call_timeout=999.0)
    clamped = caps.clamp_to_2x_defaults()
    assert clamped.max_rounds == DEFAULT_MAX_ROUNDS * 2
    assert clamped.max_parallel == DEFAULT_MAX_PARALLEL * 2


def test_run_caps_relax_env_disables_clamp(monkeypatch) -> None:
    monkeypatch.setenv("LITERATURE_MCP_RELAX_CAPS", "1")
    caps = RunCaps(max_rounds=99, max_total_seconds=999.0, max_parallel=99, per_call_timeout=999.0)
    clamped = caps.clamp_to_2x_defaults()
    assert clamped.max_rounds == 99


@pytest.mark.asyncio
async def test_runner_natural_exit_when_no_tool_calls() -> None:
    cfg = _server()

    async def chat_call(messages, tools):
        return {"content": [{"type": "text", "text": "hello world"}]}

    runner = McpToolUseRunner(
        manager=_FakeManager(),
        catalog=_FakeCatalog(),
        servers=[cfg],
        catalog_snapshot=[(cfg, [_tool("echo")])],
    )
    result = await runner.run(provider="Claude", initial_messages=[], chat_call=chat_call)
    assert result.stopped_reason == "no_tools"
    assert result.rounds == 1
    assert result.final_text == "hello world"
    assert result.transcript == []


@pytest.mark.asyncio
async def test_runner_one_tool_round_then_finishes() -> None:
    cfg = _server()
    mgr = _FakeManager()
    cat = _FakeCatalog(tools=[_tool("echo")])
    state = {"round": 0}

    async def chat_call(messages, tools):
        state["round"] += 1
        if state["round"] == 1:
            # tool_use round
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_xyz",
                        "name": "mcp__demo__echo",
                        "input": {"text": "hi"},
                    }
                ]
            }
        # final round: plain text
        return {"content": [{"type": "text", "text": "DONE"}]}

    runner = McpToolUseRunner(
        manager=mgr, catalog=cat, servers=[cfg], catalog_snapshot=[(cfg, [_tool("echo")])],
    )
    result = await runner.run(provider="Claude", initial_messages=[], chat_call=chat_call)
    assert result.stopped_reason == "natural"
    assert result.rounds == 2
    assert result.final_text == "DONE"
    assert len(result.transcript) == 1
    assert result.transcript[0].tool_name == "echo"
    assert mgr.calls == [(cfg.server_id, "echo", {"text": "hi"})]


@pytest.mark.asyncio
async def test_runner_hits_max_rounds_cap() -> None:
    cfg = _server()
    mgr = _FakeManager()
    cat = _FakeCatalog(tools=[_tool("echo")])

    async def chat_call(messages, tools):
        # Always returns a tool call → loop never naturally ends.
        return {
            "content": [
                {
                    "type": "tool_use",
                    "id": f"call_{len(messages)}",
                    "name": "mcp__demo__echo",
                    "input": {},
                }
            ]
        }

    caps = RunCaps(max_rounds=2, max_total_seconds=10.0, max_parallel=1, per_call_timeout=5.0)
    runner = McpToolUseRunner(
        manager=mgr, catalog=cat, servers=[cfg], catalog_snapshot=[(cfg, [_tool("echo")])], caps=caps,
    )
    result = await runner.run(provider="Claude", initial_messages=[], chat_call=chat_call)
    assert result.stopped_reason == "max_rounds"
    assert result.rounds == 2
    assert len(result.transcript) == 2


@pytest.mark.asyncio
async def test_runner_openai_shape_round_trip() -> None:
    cfg = _server()
    mgr = _FakeManager()
    cat = _FakeCatalog(tools=[_tool("echo")])
    state = {"round": 0}

    async def chat_call(messages, tools):
        state["round"] += 1
        if state["round"] == 1:
            return {
                "choices": [{
                    "message": {
                        "content": None,
                        "tool_calls": [{
                            "id": "tc_1",
                            "type": "function",
                            "function": {"name": "mcp__demo__echo", "arguments": '{"text":"hi"}'},
                        }],
                    }
                }]
            }
        return {"choices": [{"message": {"content": "OK", "tool_calls": []}}]}

    runner = McpToolUseRunner(
        manager=mgr, catalog=cat, servers=[cfg], catalog_snapshot=[(cfg, [_tool("echo")])],
    )
    result = await runner.run(provider="DeepSeek", initial_messages=[], chat_call=chat_call)
    assert result.stopped_reason == "natural"
    assert result.final_text == "OK"
    assert mgr.calls == [(cfg.server_id, "echo", {"text": "hi"})]
