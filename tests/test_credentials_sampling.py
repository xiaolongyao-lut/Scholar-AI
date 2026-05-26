"""Test I5/D2: Credential sampling endpoint (2026-05-26).

Verify /api/credentials/sample selects credentials by category + strategy_hint.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Add literature_assistant/core to sys.path to match app's import context
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
from python_adapter_server import app
from routers.credentials_router import get_credential_store, set_credential_store


@pytest.fixture(scope="function")
def tmp_store(tmp_path_factory):
    """Isolated credential store for each test."""
    tmp_dir = tmp_path_factory.mktemp("creds")
    store_path = tmp_dir / "test_credentials.json"
    store = RuntimeCredentialStore(path=store_path)
    # Set module-level singleton to test store
    set_credential_store(store)
    yield store
    # Reset after test
    set_credential_store(None)


@pytest.fixture
def client(tmp_store):
    """TestClient that uses the module-level store set by tmp_store fixture."""
    yield TestClient(app)


class TestCredentialSampling:
    """I5/D2: Credential sampling by category + strategy_hint."""

    def test_sample_exact_match(self, tmp_store, client):
        """Exact strategy_hint match returns that credential."""
        # Create credentials with different hints
        low_cred = tmp_store.create(
            RuntimeCredentialCreate(
                category=CredentialCategory.GENERATION,
                provider="openai",
                model="gpt-4",
                base_url="https://api.openai.com/v1",
                protocol=CredentialProtocol.OPENAI_CHAT_COMPLETIONS,
                api_key="sk-test-low",
                strategy_hint=CredentialStrategyHint.LOW,
                trust_source=CredentialTrustSource.ENV_CONFIGURED_GATEWAY,
                priority=100,
            )
        )
        high_cred = tmp_store.create(
            RuntimeCredentialCreate(
                category=CredentialCategory.GENERATION,
                provider="anthropic",
                model="claude-opus-4",
                base_url="https://api.anthropic.com",
                protocol=CredentialProtocol.ANTHROPIC_MESSAGES,
                api_key="sk-ant-test-high",
                strategy_hint=CredentialStrategyHint.HIGH,
                trust_source=CredentialTrustSource.ENV_CONFIGURED_GATEWAY,
                priority=100,
            )
        )

        # Sample with strategy_hint=high
        resp = client.post("/api/credentials/sample?strategy_hint=high")
        assert resp.status_code == 200
        data = resp.json()
        # Should return high strategy credential
        assert data["strategy_hint"] == "high"
        assert data["model"] == "claude-opus-4"

    def test_sample_legacy_mapping(self, tmp_store, client):
        """Legacy strategy_hint values map to canonical tiers."""
        # Create credential with canonical LOW
        tmp_store.create(
            RuntimeCredentialCreate(
                category=CredentialCategory.GENERATION,
                provider="openai",
                model="gpt-4-mini",
                base_url="https://api.openai.com/v1",
                protocol=CredentialProtocol.OPENAI_CHAT_COMPLETIONS,
                api_key="sk-test-cheap",
                strategy_hint=CredentialStrategyHint.LOW,
                trust_source=CredentialTrustSource.ENV_CONFIGURED_GATEWAY,
            )
        )

        # Sample with legacy "cheap" -> should match LOW
        resp = client.post("/api/credentials/sample?strategy_hint=cheap")
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy_hint"] == "low"
        assert data["model"] == "gpt-4-mini"

    def test_sample_fallback_to_priority(self, tmp_store, client):
        """No exact match falls back to highest priority."""
        # Create credentials with different priorities
        tmp_store.create(
            RuntimeCredentialCreate(
                category=CredentialCategory.GENERATION,
                provider="openai",
                model="gpt-4",
                base_url="https://api.openai.com/v1",
                protocol=CredentialProtocol.OPENAI_CHAT_COMPLETIONS,
                api_key="sk-test-low-priority",
                strategy_hint=CredentialStrategyHint.MEDIUM,
                trust_source=CredentialTrustSource.ENV_CONFIGURED_GATEWAY,
                priority=200,
            )
        )
        tmp_store.create(
            RuntimeCredentialCreate(
                category=CredentialCategory.GENERATION,
                provider="anthropic",
                model="claude-sonnet-4",
                base_url="https://api.anthropic.com",
                protocol=CredentialProtocol.ANTHROPIC_MESSAGES,
                api_key="sk-ant-test-high-priority",
                strategy_hint=CredentialStrategyHint.MEDIUM,
                trust_source=CredentialTrustSource.ENV_CONFIGURED_GATEWAY,
                priority=50,
            )
        )

        # Sample with strategy_hint=max (no exact match)
        resp = client.post("/api/credentials/sample?strategy_hint=max")
        assert resp.status_code == 200
        data = resp.json()
        # Should return high_priority (priority=50 < 200)
        assert data["model"] == "claude-sonnet-4"
        assert data["priority"] == 50

    def test_sample_category_filter(self, tmp_store, client):
        """Category filter isolates credentials."""
        # Create generation and embedding credentials
        tmp_store.create(
            RuntimeCredentialCreate(
                category=CredentialCategory.GENERATION,
                provider="openai",
                model="gpt-4",
                base_url="https://api.openai.com/v1",
                protocol=CredentialProtocol.OPENAI_CHAT_COMPLETIONS,
                api_key="sk-test-gen",
                strategy_hint=CredentialStrategyHint.MEDIUM,
                trust_source=CredentialTrustSource.ENV_CONFIGURED_GATEWAY,
            )
        )
        tmp_store.create(
            RuntimeCredentialCreate(
                category=CredentialCategory.EMBEDDING,
                provider="openai",
                model="text-embedding-3-large",
                base_url="https://api.openai.com/v1",
                protocol=CredentialProtocol.EMBEDDINGS,
                api_key="sk-test-embed",
                strategy_hint=CredentialStrategyHint.MEDIUM,
                trust_source=CredentialTrustSource.ENV_CONFIGURED_GATEWAY,
            )
        )

        # Sample embedding category
        resp = client.post("/api/credentials/sample?category=embedding")
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "embedding"
        assert data["model"] == "text-embedding-3-large"

    def test_sample_no_enabled_credentials(self, tmp_store, client):
        """404 when no enabled credentials in category."""
        # Create disabled credential
        tmp_store.create(
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

        resp = client.post("/api/credentials/sample")
        assert resp.status_code == 404
        # The log shows the error is raised correctly, just verify status code
        # (The response body structure may vary based on error handling middleware)

    def test_sample_default_category_generation(self, tmp_store, client):
        """Default category is 'generation'."""
        tmp_store.create(
            RuntimeCredentialCreate(
                category=CredentialCategory.GENERATION,
                provider="openai",
                model="gpt-4",
                base_url="https://api.openai.com/v1",
                protocol=CredentialProtocol.OPENAI_CHAT_COMPLETIONS,
                api_key="sk-test-gen",
                trust_source=CredentialTrustSource.ENV_CONFIGURED_GATEWAY,
            )
        )

        # No category param -> defaults to generation
        resp = client.post("/api/credentials/sample")
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "generation"
        assert data["model"] == "gpt-4"

    def test_sample_default_strategy_medium(self, tmp_store, client):
        """Default strategy_hint is 'medium'."""
        tmp_store.create(
            RuntimeCredentialCreate(
                category=CredentialCategory.GENERATION,
                provider="openai",
                model="gpt-4",
                base_url="https://api.openai.com/v1",
                protocol=CredentialProtocol.OPENAI_CHAT_COMPLETIONS,
                api_key="sk-test-medium",
                strategy_hint=CredentialStrategyHint.MEDIUM,
                trust_source=CredentialTrustSource.ENV_CONFIGURED_GATEWAY,
            )
        )

        # No strategy_hint param -> defaults to medium
        resp = client.post("/api/credentials/sample")
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy_hint"] == "medium"

    def test_sample_masked_api_key(self, tmp_store, client):
        """Response masks api_key."""
        tmp_store.create(
            RuntimeCredentialCreate(
                category=CredentialCategory.GENERATION,
                provider="openai",
                model="gpt-4",
                base_url="https://api.openai.com/v1",
                protocol=CredentialProtocol.OPENAI_CHAT_COMPLETIONS,
                api_key="sk-test-secret-key-12345",
                trust_source=CredentialTrustSource.ENV_CONFIGURED_GATEWAY,
            )
        )

        resp = client.post("/api/credentials/sample")
        assert resp.status_code == 200
        data = resp.json()
        # api_key should be masked (RuntimeCredentialPublic uses "api_key_masked" field)
        assert "api_key_masked" in data
        masked = data["api_key_masked"]
        assert masked.startswith("sk-t")
        assert masked.endswith("2345")
        assert "secret" not in masked
