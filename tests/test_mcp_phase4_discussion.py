"""Phase 4 tests: discussion ↔ MCP integration via
make_mcp_enabled_invoke_factory.

The factory wraps the default invoke_agent and routes through chat_ask
with mcp_server_ids when the run carries mcp_overrides AND the env flag
is on. Tests verify:

  1. With env off → factory returns the base invoke (no MCP path).
  2. With env on but mcp_overrides is None → no MCP path.
  3. With env on and server_ids non-empty → invoke calls chat_ask with
     mcp_server_ids populated (we monkeypatch chat_ask to assert the
     ChatRequest shape).
  4. per_agent is accepted by the model but ignored (warning logged).
  5. set_invoke_agent_factory(None) restores production wrapping behavior.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

import pytest

from model_dispatcher import DispatchCandidate
from models.discussion import (
    DiscussionAgentConfig,
    DiscussionLLMConfig,
    DiscussionMcpOverrides,
    DiscussionRunConfig,
)
from routers import discussion_advanced_router as r
from routers import chat_router as cr


def _candidate(agent_id: str = "agent_a") -> DispatchCandidate:
    return DispatchCandidate(
        candidate_id=f"cand_{agent_id}",
        agent_id=agent_id,
        provider="DeepSeek",
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        metadata={"api_key": "sk-test-1234567890", "temperature": 0.5, "max_tokens": 1024},  # pragma: allowlist secret
    )


def _run_config(*, with_mcp: bool, server_ids: list[str] | None = None) -> DiscussionRunConfig:
    return DiscussionRunConfig(
        query="hello",
        agent_configs=[
            DiscussionAgentConfig(
                agent_id="agent_a",
                role="proposer",
                llm=DiscussionLLMConfig(
                    provider="DeepSeek",
                    model="deepseek-chat",
                    base_url="https://api.deepseek.com",
                    api_key="sk-test-1234567890",  # noqa: pragma: allowlist secret
                ),
            )
        ],
        evidence_mode="none",
        mcp_overrides=(
            DiscussionMcpOverrides(server_ids=server_ids or [])
            if with_mcp
            else None
        ),
    )


# ---------------------------------------------------------------------------
# 1. Env off → no MCP wrapping behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_factory_no_mcp_when_env_off(monkeypatch) -> None:
    monkeypatch.delenv("LITERATURE_ENABLE_MCP_TOOLS", raising=False)
    captured = {}

    async def fake_chat_ask(req: cr.ChatRequest):
        captured["req"] = req
        return cr.ChatResponse(answer="ok", model="m")

    monkeypatch.setattr(cr, "chat_ask", fake_chat_ask)
    cfg = _run_config(with_mcp=True, server_ids=["mcp_demo"])
    factory = r.make_mcp_enabled_invoke_factory()
    invoke = factory(cfg)
    out = await invoke(_candidate(), "hi")
    assert out == "ok"
    # Default factory path uses chat_ask without MCP fields.
    assert captured["req"].mcp_server_ids is None


# ---------------------------------------------------------------------------
# 2. Env on but no overrides → no MCP wrapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_factory_no_mcp_when_overrides_none(monkeypatch) -> None:
    monkeypatch.setenv("LITERATURE_ENABLE_MCP_TOOLS", "1")
    captured = {}

    async def fake_chat_ask(req: cr.ChatRequest):
        captured["req"] = req
        return cr.ChatResponse(answer="ok", model="m")

    monkeypatch.setattr(cr, "chat_ask", fake_chat_ask)
    cfg = _run_config(with_mcp=False)
    factory = r.make_mcp_enabled_invoke_factory()
    invoke = factory(cfg)
    await invoke(_candidate(), "hi")
    assert captured["req"].mcp_server_ids is None


# ---------------------------------------------------------------------------
# 3. Env on + server_ids → chat_ask called with MCP fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_factory_routes_through_mcp_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("LITERATURE_ENABLE_MCP_TOOLS", "1")
    captured = {}

    async def fake_chat_ask(req: cr.ChatRequest):
        captured["req"] = req
        return cr.ChatResponse(answer="ANSWER", model="m")

    monkeypatch.setattr(cr, "chat_ask", fake_chat_ask)
    cfg = _run_config(with_mcp=True, server_ids=["mcp_demo", "mcp_b"])
    factory = r.make_mcp_enabled_invoke_factory()
    invoke = factory(cfg)
    answer = await invoke(_candidate(), "go")
    assert answer == "ANSWER"
    assert captured["req"].mcp_server_ids == ["mcp_demo", "mcp_b"]
    assert captured["req"].mcp_allow_high_risk_tools is False


@pytest.mark.asyncio
async def test_factory_propagates_high_risk_flag(monkeypatch) -> None:
    monkeypatch.setenv("LITERATURE_ENABLE_MCP_TOOLS", "1")
    captured = {}

    async def fake_chat_ask(req: cr.ChatRequest):
        captured["req"] = req
        return cr.ChatResponse(answer="OK", model="m")

    monkeypatch.setattr(cr, "chat_ask", fake_chat_ask)
    cfg = _run_config(with_mcp=True, server_ids=["mcp_demo"])
    cfg = cfg.model_copy(update={"mcp_overrides": DiscussionMcpOverrides(
        server_ids=["mcp_demo"], allow_high_risk_tools=True,
    )})
    invoke = r.make_mcp_enabled_invoke_factory()(cfg)
    await invoke(_candidate(), "go")
    assert captured["req"].mcp_allow_high_risk_tools is True


# ---------------------------------------------------------------------------
# 4. per_agent is accepted but ignored (warning logged)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_factory_logs_warning_when_per_agent_supplied(monkeypatch, caplog) -> None:
    monkeypatch.setenv("LITERATURE_ENABLE_MCP_TOOLS", "1")

    async def fake_chat_ask(req: cr.ChatRequest):
        return cr.ChatResponse(answer="x", model="m")

    monkeypatch.setattr(cr, "chat_ask", fake_chat_ask)
    cfg = _run_config(with_mcp=True, server_ids=["mcp_demo"])
    cfg = cfg.model_copy(update={"mcp_overrides": DiscussionMcpOverrides(
        server_ids=["mcp_demo"], per_agent={"agent_a": ["mcp_demo"]},
    )})
    with caplog.at_level(logging.WARNING, logger="DiscussionAdvancedRouter"):
        invoke = r.make_mcp_enabled_invoke_factory()(cfg)
        await invoke(_candidate(), "hi")
    msgs = [rec.message for rec in caplog.records]
    assert any("per_agent" in m and "ignored" in m for m in msgs)


# ---------------------------------------------------------------------------
# 5. Empty server_ids = audit-recorded zero-server (falls back to base)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_factory_empty_server_ids_falls_back_to_base(monkeypatch) -> None:
    monkeypatch.setenv("LITERATURE_ENABLE_MCP_TOOLS", "1")
    captured = {}

    async def fake_chat_ask(req: cr.ChatRequest):
        captured["req"] = req
        return cr.ChatResponse(answer="z", model="m")

    monkeypatch.setattr(cr, "chat_ask", fake_chat_ask)
    cfg = _run_config(with_mcp=True, server_ids=[])
    invoke = r.make_mcp_enabled_invoke_factory()(cfg)
    await invoke(_candidate(), "hi")
    # Empty list = no MCP route → mcp_server_ids stays unset on the request.
    assert captured["req"].mcp_server_ids is None


# ---------------------------------------------------------------------------
# 6. _get_invoke_factory wraps default in production unless test injects
# ---------------------------------------------------------------------------


def test_get_invoke_factory_uses_mcp_wrapped_default(monkeypatch) -> None:
    r.set_invoke_agent_factory(None)
    factory = r._get_invoke_factory()
    # Cannot easily probe identity, but confirm calling it with mcp_overrides
    # selects the MCP path when env is on.
    monkeypatch.setenv("LITERATURE_ENABLE_MCP_TOOLS", "1")
    cfg = _run_config(with_mcp=True, server_ids=["mcp_demo"])
    invoke = factory(cfg)
    assert invoke is not None  # smoke


def test_get_invoke_factory_honors_test_injection(monkeypatch) -> None:
    sentinel_called = {"n": 0}

    async def stub_invoke(candidate, prompt):
        sentinel_called["n"] += 1
        return "stub"

    def stub_factory(config):
        return stub_invoke

    r.set_invoke_agent_factory(stub_factory)
    try:
        factory = r._get_invoke_factory()
        assert factory is stub_factory
    finally:
        r.set_invoke_agent_factory(None)
