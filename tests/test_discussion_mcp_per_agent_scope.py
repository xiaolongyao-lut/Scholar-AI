"""Test J8: MCP per-agent scope (2026-05-26).

Verify scope_type=agent isolates MCP server lists per agent_id/role.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add literature_assistant/core to sys.path
core_path = Path(__file__).parent.parent / "literature_assistant" / "core"
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))

from models.discussion import (
    DiscussionAgentConfig,
    DiscussionAgentRole,
    DiscussionMcpOverrides,
    DiscussionRunConfig,
    McpScopeType,
)
from routers.discussion_advanced_router import make_mcp_enabled_invoke_factory


class TestMcpPerAgentScope:
    """J8: MCP per-agent scope isolation."""

    @pytest.fixture
    def mock_chat_mcp_integration(self):
        """Mock chat_mcp_integration.is_mcp_tools_enabled() to return True."""
        with patch("routers.chat_mcp_integration.is_mcp_tools_enabled", return_value=True):
            yield

    @pytest.fixture
    def mock_chat_ask(self):
        """Mock chat_ask to capture mcp_server_ids."""
        captured_calls = []

        async def fake_chat_ask(req):
            captured_calls.append({
                "agent_id": getattr(req, "agent_id", None),
                "mcp_server_ids": req.mcp_server_ids,
            })
            response = MagicMock()
            response.answer = "test response"
            return response

        with patch("routers.chat_router.chat_ask", side_effect=fake_chat_ask):
            yield captured_calls

    def test_scope_type_surface_all_agents_share(self, mock_chat_mcp_integration, mock_chat_ask):
        """scope_type=surface: all agents get same server_ids."""
        from models.discussion import DiscussionEvidenceMode
        config = DiscussionRunConfig(
            query="test query",
            agent_configs=[
                DiscussionAgentConfig(agent_id="agent1", role=DiscussionAgentRole.PROPOSER),
                DiscussionAgentConfig(agent_id="agent2", role=DiscussionAgentRole.CRITIC),
            ],
            evidence_mode=DiscussionEvidenceMode.NONE,
            mcp_overrides=DiscussionMcpOverrides(
                scope_type=McpScopeType.SURFACE,
                server_ids=["mcp_server_a", "mcp_server_b"],
            ),
        )

        base_invoke = AsyncMock(return_value="base response")
        factory = make_mcp_enabled_invoke_factory(lambda cfg: base_invoke)
        invoke = factory(config)

        # Simulate two agent invocations
        from model_dispatcher import DispatchCandidate
        candidate1 = DispatchCandidate(
            candidate_id="c1",
            agent_id="agent1",
            role="proposer",
            provider="openai",
            model="gpt-4",
            base_url="https://api.openai.com/v1",
            metadata={"api_key": "sk-test1"},
        )
        candidate2 = DispatchCandidate(
            candidate_id="c2",
            agent_id="agent2",
            role="critic",
            provider="openai",
            model="gpt-4",
            base_url="https://api.openai.com/v1",
            metadata={"api_key": "sk-test2"},
        )

        import asyncio
        asyncio.run(invoke(candidate1, "prompt1"))
        asyncio.run(invoke(candidate2, "prompt2"))

        # Both agents should get the same server_ids
        assert len(mock_chat_ask) == 2
        assert mock_chat_ask[0]["mcp_server_ids"] == ["mcp_server_a", "mcp_server_b"]
        assert mock_chat_ask[1]["mcp_server_ids"] == ["mcp_server_a", "mcp_server_b"]

    def test_scope_type_agent_per_agent_isolation(self, mock_chat_mcp_integration, mock_chat_ask):
        """scope_type=agent with per_agent: each agent gets isolated server list."""
        from models.discussion import DiscussionEvidenceMode
        config = DiscussionRunConfig(
            query="test query",
            agent_configs=[
                DiscussionAgentConfig(agent_id="agent1", role=DiscussionAgentRole.PROPOSER),
                DiscussionAgentConfig(agent_id="agent2", role=DiscussionAgentRole.CRITIC),
            ],
            evidence_mode=DiscussionEvidenceMode.NONE,
            mcp_overrides=DiscussionMcpOverrides(
                scope_type=McpScopeType.AGENT,
                server_ids=["mcp_fallback"],
                per_agent={
                    "agent1": ["mcp_server_a"],
                    "agent2": ["mcp_server_b", "mcp_server_c"],
                },
            ),
        )

        base_invoke = AsyncMock(return_value="base response")
        factory = make_mcp_enabled_invoke_factory(lambda cfg: base_invoke)
        invoke = factory(config)

        from model_dispatcher import DispatchCandidate
        candidate1 = DispatchCandidate(
            candidate_id="c1",
            agent_id="agent1",
            role="proposer",
            provider="openai",
            model="gpt-4",
            base_url="https://api.openai.com/v1",
            metadata={"api_key": "sk-test1"},
        )
        candidate2 = DispatchCandidate(
            candidate_id="c2",
            agent_id="agent2",
            role="critic",
            provider="openai",
            model="gpt-4",
            base_url="https://api.openai.com/v1",
            metadata={"api_key": "sk-test2"},
        )

        import asyncio
        asyncio.run(invoke(candidate1, "prompt1"))
        asyncio.run(invoke(candidate2, "prompt2"))

        # Each agent should get its own server list
        assert len(mock_chat_ask) == 2
        assert mock_chat_ask[0]["mcp_server_ids"] == ["mcp_server_a"]
        assert mock_chat_ask[1]["mcp_server_ids"] == ["mcp_server_b", "mcp_server_c"]

    def test_scope_type_agent_per_role_fallback(self, mock_chat_mcp_integration, mock_chat_ask):
        """scope_type=agent with per_role: agents without per_agent entry use per_role."""
        from models.discussion import DiscussionEvidenceMode
        config = DiscussionRunConfig(
            query="test query",
            agent_configs=[
                DiscussionAgentConfig(agent_id="agent1", role=DiscussionAgentRole.PROPOSER),
                DiscussionAgentConfig(agent_id="agent2", role=DiscussionAgentRole.CRITIC),
                DiscussionAgentConfig(agent_id="agent3", role=DiscussionAgentRole.PROPOSER),
            ],
            evidence_mode=DiscussionEvidenceMode.NONE,
            mcp_overrides=DiscussionMcpOverrides(
                scope_type=McpScopeType.AGENT,
                server_ids=["mcp_fallback"],
                per_agent={
                    "agent1": ["mcp_agent1_only"],
                },
                per_role={
                    "proposer": ["mcp_proposer_role"],
                    "critic": ["mcp_critic_role"],
                },
            ),
        )

        base_invoke = AsyncMock(return_value="base response")
        factory = make_mcp_enabled_invoke_factory(lambda cfg: base_invoke)
        invoke = factory(config)

        from model_dispatcher import DispatchCandidate
        candidate1 = DispatchCandidate(
            candidate_id="c1",
            agent_id="agent1",
            role="proposer",
            provider="openai",
            model="gpt-4",
            base_url="https://api.openai.com/v1",
            metadata={"api_key": "sk-test1"},
        )
        candidate2 = DispatchCandidate(
            candidate_id="c2",
            agent_id="agent2",
            role="critic",
            provider="openai",
            model="gpt-4",
            base_url="https://api.openai.com/v1",
            metadata={"api_key": "sk-test2"},
        )
        candidate3 = DispatchCandidate(
            candidate_id="c3",
            agent_id="agent3",
            role="proposer",
            provider="openai",
            model="gpt-4",
            base_url="https://api.openai.com/v1",
            metadata={"api_key": "sk-test3"},
        )

        import asyncio
        asyncio.run(invoke(candidate1, "prompt1"))
        asyncio.run(invoke(candidate2, "prompt2"))
        asyncio.run(invoke(candidate3, "prompt3"))

        # agent1: per_agent override
        # agent2: per_role fallback (critic)
        # agent3: per_role fallback (proposer)
        assert len(mock_chat_ask) == 3
        assert mock_chat_ask[0]["mcp_server_ids"] == ["mcp_agent1_only"]
        assert mock_chat_ask[1]["mcp_server_ids"] == ["mcp_critic_role"]
        assert mock_chat_ask[2]["mcp_server_ids"] == ["mcp_proposer_role"]

    def test_scope_type_agent_server_ids_fallback(self, mock_chat_mcp_integration, mock_chat_ask):
        """scope_type=agent: agents without per_agent/per_role use server_ids fallback."""
        from models.discussion import DiscussionEvidenceMode
        config = DiscussionRunConfig(
            query="test query",
            agent_configs=[
                DiscussionAgentConfig(agent_id="agent1", role=DiscussionAgentRole.PROPOSER),
                DiscussionAgentConfig(agent_id="agent2", role=DiscussionAgentRole.CUSTOM),
            ],
            evidence_mode=DiscussionEvidenceMode.NONE,
            mcp_overrides=DiscussionMcpOverrides(
                scope_type=McpScopeType.AGENT,
                server_ids=["mcp_fallback_a", "mcp_fallback_b"],
                per_agent={
                    "agent1": ["mcp_agent1"],
                },
            ),
        )

        base_invoke = AsyncMock(return_value="base response")
        factory = make_mcp_enabled_invoke_factory(lambda cfg: base_invoke)
        invoke = factory(config)

        from model_dispatcher import DispatchCandidate
        candidate1 = DispatchCandidate(
            candidate_id="c1",
            agent_id="agent1",
            role="proposer",
            provider="openai",
            model="gpt-4",
            base_url="https://api.openai.com/v1",
            metadata={"api_key": "sk-test1"},
        )
        candidate2 = DispatchCandidate(
            candidate_id="c2",
            agent_id="agent2",
            role="custom",
            provider="openai",
            model="gpt-4",
            base_url="https://api.openai.com/v1",
            metadata={"api_key": "sk-test2"},
        )

        import asyncio
        asyncio.run(invoke(candidate1, "prompt1"))
        asyncio.run(invoke(candidate2, "prompt2"))

        # agent1: per_agent
        # agent2: server_ids fallback (no per_agent, no per_role for "custom")
        assert len(mock_chat_ask) == 2
        assert mock_chat_ask[0]["mcp_server_ids"] == ["mcp_agent1"]
        assert mock_chat_ask[1]["mcp_server_ids"] == ["mcp_fallback_a", "mcp_fallback_b"]

    def test_scope_type_agent_all_empty_returns_base_invoke(self, mock_chat_mcp_integration):
        """scope_type=agent with all empty server lists returns base_invoke."""
        from models.discussion import DiscussionEvidenceMode
        config = DiscussionRunConfig(
            query="test query",
            agent_configs=[
                DiscussionAgentConfig(agent_id="agent1", role=DiscussionAgentRole.PROPOSER),
            ],
            evidence_mode=DiscussionEvidenceMode.NONE,
            mcp_overrides=DiscussionMcpOverrides(
                scope_type=McpScopeType.AGENT,
                server_ids=[],
                per_agent={"agent1": []},
            ),
        )

        base_invoke = AsyncMock(return_value="base response")
        factory = make_mcp_enabled_invoke_factory(lambda cfg: base_invoke)
        invoke = factory(config)

        # Should return base_invoke (no MCP wrapper)
        assert invoke == base_invoke
