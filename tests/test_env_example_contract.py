from __future__ import annotations

import importlib
from typing import Any


def _clear_runtime_env(monkeypatch: Any) -> Any:
    """Reload runtime env helpers with dotenv disabled for deterministic tests."""

    monkeypatch.setenv("RUNTIME_ENV_DISABLE_DOTENV", "1")
    import runtime_env

    runtime_env._repo_env.cache_clear()
    return importlib.reload(runtime_env)


def test_env_example_embedding_variables_resolve(monkeypatch: Any) -> None:
    """The public .env.example embedding template must map to runtime config."""

    runtime_env = _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("EMBEDDING_API_KEY", "embedding-key")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://embedding.example.com/v1")
    monkeypatch.setenv("EMBEDDING_MODEL", "embedding-model")
    monkeypatch.setenv("EMBEDDING_KEY_PROBE_DISABLE", "1")

    api_key, base_url, model = runtime_env.resolve_embedding_config(
        default_base_url="https://default.example.com/v1",
        default_model="default-embedding",
    )

    assert api_key == "embedding-key"
    assert base_url == "https://embedding.example.com/v1"
    assert model == "embedding-model"


def test_env_example_rerank_variables_resolve(monkeypatch: Any) -> None:
    """The public .env.example rerank template must map to runtime config."""

    _clear_runtime_env(monkeypatch)
    import reranker_client

    monkeypatch.setenv("RERANK_API_KEY", "rerank-key")
    monkeypatch.setenv("RERANK_BASE_URL", "https://rerank.example.com/v1/rerank")
    monkeypatch.setenv("RERANK_MODEL", "rerank-model")
    monkeypatch.setenv("RERANK_KEY_PROBE_DISABLE", "1")

    api_key, base_url, model = reranker_client.resolve_rerank_config()

    assert api_key == "rerank-key"
    assert base_url == "https://rerank.example.com/v1/rerank"
    assert model == "rerank-model"


def test_env_example_chat_variables_resolve(monkeypatch: Any) -> None:
    """The public .env.example chat template must map to SmartRead LLM config."""

    runtime_env = _clear_runtime_env(monkeypatch)
    monkeypatch.setenv("CHAT_API_KEY", "chat-key")
    monkeypatch.setenv("CHAT_BASE_URL", "https://chat.example.com/v1")
    monkeypatch.setenv("CHAT_MODEL", "chat-model")

    api_key, base_url, model = runtime_env.resolve_llm_config(
        default_base_url="https://default.example.com/v1",
        default_model="default-chat",
    )

    assert api_key == "chat-key"
    assert base_url == "https://chat.example.com/v1"
    assert model == "chat-model"
