"""Test D1: Runtime credentials for Discussion (2026-05-26).

Verify Discussion run/stream support credential_id and strategy_hint/category selection.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add literature_assistant/core to sys.path
core_path = Path(__file__).parent.parent / "literature_assistant" / "core"
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))

from credential_store import RuntimeCredentialStore
from models.credentials import (
    CredentialCategory,
    CredentialProtocol,
    CredentialStrategyHint,
    CredentialTrustSource,
    RuntimeCredentialCreate,
)
from models.discussion import (
    DiscussionAgentConfig,
    DiscussionAgentRole,
    DiscussionEvidenceMode,
    DiscussionRunConfig,
)
from discussion_orchestrator import (
    DiscussionCredentialMissingError,
    _default_credential_resolver,
    _resolve_agent_endpoint,
)


@pytest.fixture(scope="function")
def tmp_store(tmp_path_factory):
    """Isolated credential store for each test."""
    tmp_dir = tmp_path_factory.mktemp("creds")
    store_path = tmp_dir / "test_credentials.json"
    store = RuntimeCredentialStore(path=store_path)
    # Patch the module-level singleton
    with patch("credential_store.RuntimeCredentialStore") as mock_cls:
        mock_cls.return_value = store
        yield store


class TestDiscussionCredentialId:
    """D1: credential_id resolution and validation."""

    def test_credential_id_resolves_to_endpoint(self, tmp_store):
        """Valid credential_id resolves to endpoint dict."""
        cred = tmp_store.create(
            RuntimeCredentialCreate(
                category=CredentialCategory.GENERATION,
                provider="openai",
                model="gpt-4",
                base_url="https://api.openai.com/v1",
                protocol=CredentialProtocol.OPENAI_CHAT_COMPLETIONS,
                api_key="sk-test-credential-id",
                trust_source=CredentialTrustSource.ENV_CONFIGURED_GATEWAY,
            )
        )

        endpoint = _default_credential_resolver(cred.credential_id)
        assert endpoint["provider"] == "openai"
        assert endpoint["model"] == "gpt-4"
        assert endpoint["base_url"] == "https://api.openai.com/v1"
        assert endpoint["api_key"] == "sk-test-credential-id"
        assert endpoint["protocol"] == "openai_chat_completions"

    def test_credential_id_not_found_raises_error(self, tmp_store):
        """Non-existent credential_id raises DiscussionCredentialMissingError."""
        with pytest.raises(DiscussionCredentialMissingError) as exc_info:
            _default_credential_resolver("nonexistent")
        assert "凭证不存在或已被删除" in str(exc_info.value)
        assert "nonexistent" not in str(exc_info.value)

    def test_credential_id_disabled_raises_error(self, tmp_store):
        """Disabled credential raises DiscussionCredentialMissingError."""
        cred = tmp_store.create(
            RuntimeCredentialCreate(
                category=CredentialCategory.GENERATION,
                provider="openai",
                model="gpt-4",
                base_url="https://api.openai.com/v1",
                protocol=CredentialProtocol.OPENAI_CHAT_COMPLETIONS,
                api_key="sk-test-disabled",
                enabled=False,
                trust_source=CredentialTrustSource.ENV_CONFIGURED_GATEWAY,
            )
        )

        with pytest.raises(DiscussionCredentialMissingError) as exc_info:
            _default_credential_resolver(cred.credential_id)
        assert "选择的凭证已停用" in str(exc_info.value)
        assert cred.credential_id not in str(exc_info.value)


class TestDiscussionStrategyHint:
    """D1: strategy_hint + category dynamic credential sampling."""

    def test_strategy_hint_samples_credential(self, tmp_store):
        """strategy_hint + category samples matching credential."""
        tmp_store.create(
            RuntimeCredentialCreate(
                category=CredentialCategory.GENERATION,
                provider="openai",
                model="gpt-4",
                base_url="https://api.openai.com/v1",
                protocol=CredentialProtocol.OPENAI_CHAT_COMPLETIONS,
                api_key="sk-test-high",
                strategy_hint=CredentialStrategyHint.HIGH,
                trust_source=CredentialTrustSource.ENV_CONFIGURED_GATEWAY,
            )
        )

        agent = DiscussionAgentConfig(
            agent_id="agent1",
            role=DiscussionAgentRole.PROPOSER,
            strategy_hint="high",
            category="generation",
        )

        endpoint = _resolve_agent_endpoint(agent, _default_credential_resolver)
        assert endpoint["provider"] == "openai"
        assert endpoint["model"] == "gpt-4"
        assert endpoint["api_key"] == "sk-test-high"

    def test_strategy_hint_defaults_to_generation_category(self, tmp_store):
        """strategy_hint without category defaults to generation."""
        tmp_store.create(
            RuntimeCredentialCreate(
                category=CredentialCategory.GENERATION,
                provider="anthropic",
                model="claude-opus-4",
                base_url="https://api.anthropic.com",
                protocol=CredentialProtocol.ANTHROPIC_MESSAGES,
                api_key="sk-ant-test-medium",
                strategy_hint=CredentialStrategyHint.MEDIUM,
                trust_source=CredentialTrustSource.ENV_CONFIGURED_GATEWAY,
            )
        )

        agent = DiscussionAgentConfig(
            agent_id="agent1",
            role=DiscussionAgentRole.PROPOSER,
            strategy_hint="medium",
        )

        endpoint = _resolve_agent_endpoint(agent, _default_credential_resolver)
        assert endpoint["model"] == "claude-opus-4"

    def test_strategy_hint_no_match_raises_error(self, tmp_store):
        """strategy_hint with no matching credentials raises error."""
        # Create only embedding credential
        tmp_store.create(
            RuntimeCredentialCreate(
                category=CredentialCategory.EMBEDDING,
                provider="openai",
                model="text-embedding-3-large",
                base_url="https://api.openai.com/v1",
                protocol=CredentialProtocol.EMBEDDINGS,
                api_key="sk-test-embed",
                trust_source=CredentialTrustSource.ENV_CONFIGURED_GATEWAY,
            )
        )

        agent = DiscussionAgentConfig(
            agent_id="agent1",
            role=DiscussionAgentRole.PROPOSER,
            strategy_hint="high",
            category="generation",
        )

        with pytest.raises(DiscussionCredentialMissingError, match="no enabled credentials found"):
            _resolve_agent_endpoint(agent, _default_credential_resolver)


class TestDiscussionAgentConfigValidation:
    """D1: DiscussionAgentConfig field validation."""

    def test_credential_id_and_strategy_hint_mutually_exclusive(self):
        """credential_id and strategy_hint cannot both be set."""
        with pytest.raises(ValueError, match="at most one of credential_id/llm/strategy_hint"):
            DiscussionAgentConfig(
                agent_id="agent1",
                role=DiscussionAgentRole.PROPOSER,
                credential_id="cred123",
                strategy_hint="high",
            )

    def test_category_requires_strategy_hint(self):
        """category without strategy_hint raises validation error."""
        with pytest.raises(ValueError, match="category requires strategy_hint"):
            DiscussionAgentConfig(
                agent_id="agent1",
                role=DiscussionAgentRole.PROPOSER,
                category="generation",
            )

    def test_strategy_hint_without_category_valid(self):
        """strategy_hint without category is valid (defaults to generation)."""
        agent = DiscussionAgentConfig(
            agent_id="agent1",
            role=DiscussionAgentRole.PROPOSER,
            strategy_hint="medium",
        )
        assert agent.strategy_hint == "medium"
        assert agent.category is None


class TestDiscussionEndpointResolution:
    """D1: _resolve_agent_endpoint priority order."""

    def test_llm_takes_priority_over_credential_id(self, tmp_store):
        """Inline llm takes priority over credential_id."""
        from models.discussion import DiscussionLLMConfig

        # This credential should be ignored
        tmp_store.create(
            RuntimeCredentialCreate(
                category=CredentialCategory.GENERATION,
                provider="openai",
                model="gpt-4",
                base_url="https://api.openai.com/v1",
                protocol=CredentialProtocol.OPENAI_CHAT_COMPLETIONS,
                api_key="sk-test-ignored",
                trust_source=CredentialTrustSource.ENV_CONFIGURED_GATEWAY,
            )
        )

        agent = DiscussionAgentConfig(
            agent_id="agent1",
            role=DiscussionAgentRole.PROPOSER,
            llm=DiscussionLLMConfig(
                provider="anthropic",
                model="claude-opus-4",
                base_url="https://api.anthropic.com",
                api_key="sk-ant-inline",
            ),
        )

        endpoint = _resolve_agent_endpoint(agent, _default_credential_resolver)
        assert endpoint["provider"] == "anthropic"
        assert endpoint["model"] == "claude-opus-4"
        assert endpoint["api_key"] == "sk-ant-inline"

    def test_credential_id_takes_priority_over_strategy_hint(self, tmp_store):
        """credential_id takes priority over strategy_hint."""
        cred = tmp_store.create(
            RuntimeCredentialCreate(
                category=CredentialCategory.GENERATION,
                provider="openai",
                model="gpt-4-turbo",
                base_url="https://api.openai.com/v1",
                protocol=CredentialProtocol.OPENAI_CHAT_COMPLETIONS,
                api_key="sk-test-pinned",
                trust_source=CredentialTrustSource.ENV_CONFIGURED_GATEWAY,
            )
        )

        agent = DiscussionAgentConfig(
            agent_id="agent1",
            role=DiscussionAgentRole.PROPOSER,
            credential_id=cred.credential_id,
        )

        endpoint = _resolve_agent_endpoint(agent, _default_credential_resolver)
        assert endpoint["model"] == "gpt-4-turbo"
        assert endpoint["api_key"] == "sk-test-pinned"
