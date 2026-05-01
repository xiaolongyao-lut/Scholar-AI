from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_embedding_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep provider resolution tests independent from developer .env files.

    These tests assert static routing (env-presence → provider). The new
    validity-first resolver would otherwise fire real HTTP probes against
    dummy keys and hang on DNS/TCP. Set EMBEDDING_KEY_PROBE_DISABLE=1 to
    exercise the legacy static path here; validity-first behaviour is
    covered in test_embedding_key_probe.py.
    """
    keys = (
        "RUNTIME_ENV_DISABLE_DOTENV",
        "API_KEY",
        "SILICONFLOW_API_KEY",
        "SILICONFLOW_EMBEDDING_API_KEY",
        "JINA_API_KEY",
        "EMBEDDING_API_KEY",
        "EMBEDDING_PROVIDER",
        "SILICONFLOW_EMBEDDING_BASE_URL",
        "EMBEDDING_BASE_URL",
        "BASE_URL",
        "SILICONFLOW_EMBEDDING_MODEL",
        "EMBEDDING_MODEL",
        "MODEL",
        "EMBEDDING_KEY_PROBE_DISABLE",
    )
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("RUNTIME_ENV_DISABLE_DOTENV", "1")
    monkeypatch.setenv("EMBEDDING_KEY_PROBE_DISABLE", "1")
    # Clear the per-process probe cache so other tests don't leak state in.
    from runtime_env import _KEY_PROBE_CACHE_EMBED
    _KEY_PROBE_CACHE_EMBED.clear()


def _resolve_embedding_config() -> tuple[str | None, str, str]:
    from runtime_env import resolve_embedding_config

    return resolve_embedding_config(
        default_base_url="https://api.siliconflow.cn/v1",
        default_model="Qwen/Qwen3-Embedding-8B",
    )


def test_siliconflow_key_resolves_embedding_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """SiliconFlow embedding config must not inherit rerank-only URLs or keys."""
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-embedding-key")

    api_key, base_url, model = _resolve_embedding_config()

    assert api_key == "sf-embedding-key"
    assert "siliconflow" in base_url.lower()
    assert "rerank" not in base_url.lower()
    assert model == "Qwen/Qwen3-Embedding-8B"


def test_jina_only_falls_through_to_jina(monkeypatch: pytest.MonkeyPatch) -> None:
    """With only JINA_API_KEY set, resolver must return the Jina key + Jina endpoint.

    A11.E1 closed 2026-04-25 — `_select_embedding_provider()` now falls through
    to Jina when no SiliconFlow key is present.
    """
    monkeypatch.setenv("JINA_API_KEY", "jina-embedding-key")

    api_key, base_url, _model = _resolve_embedding_config()

    assert api_key == "jina-embedding-key"
    assert "jina" in base_url.lower()


def test_both_present_prefers_siliconflow_unless_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default priority: SiliconFlow wins; EMBEDDING_PROVIDER=jina flips it.

    A11.E1 closed 2026-04-25.
    """
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-embedding-key")
    monkeypatch.setenv("JINA_API_KEY", "jina-embedding-key")

    api_key, _base_url, _model = _resolve_embedding_config()
    assert api_key == "sf-embedding-key"

    monkeypatch.setenv("EMBEDDING_PROVIDER", "jina")
    api_key, base_url, _model = _resolve_embedding_config()
    assert api_key == "jina-embedding-key"
    assert "jina" in base_url.lower()


def test_no_key_returns_none_api_key_contract() -> None:
    """With no embedding key set, resolver keeps None-return contract.

    Current runtime behavior in `resolve_embedding_config()` is no-raise +
    `api_key is None`; caller layers decide whether to fail closed, degrade,
    or skip dense retrieval.
    """
    api_key, _base_url, _model = _resolve_embedding_config()
    assert api_key is None


def test_generic_embedding_catalog_shape_uses_api_key_and_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Embedding resolver must support generic API_KEY/BASE_URL catalog entries."""
    monkeypatch.setenv("API_KEY", "catalog-embedding-key")
    monkeypatch.setenv(
        "BASE_URL",
        "https://example.test/api/v1/services/embeddings/text-embedding",
    )
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-v1")

    api_key, base_url, model = _resolve_embedding_config()

    assert api_key == "catalog-embedding-key"
    assert base_url == "https://example.test/api/v1/services/embeddings/text-embedding"
    assert model == "text-embedding-v1"


def test_resolver_falls_back_to_key_pool_embedding_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When .env is grouped, runtime resolver should consume key_pool embedding entries."""
    import key_pool
    import runtime_env as rte
    from key_pool import Credential

    monkeypatch.delenv("RUNTIME_ENV_DISABLE_DOTENV", raising=False)

    class FakePool:
        def list(self, category: str) -> list[Credential]:
            item = self.first(category)
            return [item] if item is not None else []

        def first(self, category: str) -> Credential | None:
            if category != "embedding":
                return None
            return Credential(
                category="embedding",
                provider="catalog",
                api_key="pool-embedding-key",
                base_url="https://catalog.example/v1/embeddings",
                model="catalog-embedding-model",
                line_no=1,
            )

    monkeypatch.setattr(
        rte,
        "env_value",
        lambda *names, default=None: default,
    )
    monkeypatch.setattr(key_pool, "get_pool", lambda *args, **kwargs: FakePool())

    api_key, base_url, model = rte.resolve_embedding_config(
        default_base_url="https://default.example/v1/embeddings",
        default_model="default-embedding-model",
    )

    assert api_key == "pool-embedding-key"
    assert base_url == "https://catalog.example/v1/embeddings"
    assert model == "catalog-embedding-model"


def test_resolver_key_pool_prefers_text_embedding_catalog_for_text_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Grouped env fallback should skip multimodal entries for text embedding flows."""
    import key_pool
    import runtime_env as rte
    from key_pool import Credential

    monkeypatch.delenv("RUNTIME_ENV_DISABLE_DOTENV", raising=False)

    multimodal = Credential(
        category="embedding",
        provider="catalog",
        api_key="pool-multimodal-key",
        base_url="https://catalog.example/v1/multimodal-embedding",
        model="multimodal-embedding-v1",
        line_no=1,
    )
    text = Credential(
        category="embedding",
        provider="catalog",
        api_key="pool-text-key",
        base_url="https://catalog.example/v1/embeddings",
        model="text-embedding-v4",
        line_no=2,
    )

    class FakePool:
        def list(self, category: str) -> list[Credential]:
            return [multimodal, text] if category == "embedding" else []

        def first(self, category: str) -> Credential | None:
            items = self.list(category)
            return items[0] if items else None

    monkeypatch.setattr(
        rte,
        "env_value",
        lambda *names, default=None: default,
    )
    monkeypatch.setattr(key_pool, "get_pool", lambda *args, **kwargs: FakePool())

    api_key, base_url, model = rte.resolve_embedding_config(
        default_base_url="https://default.example/v1/embeddings",
        default_model="Qwen/Qwen3-Embedding-8B",
    )

    assert api_key == "pool-text-key"
    assert base_url == "https://catalog.example/v1/embeddings"
    assert model == "text-embedding-v4"


def test_resolver_key_pool_scans_all_categories_for_embedding_shaped_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fallback should prefer embedding-shaped credentials even if headers misclassified them."""
    import key_pool
    import runtime_env as rte
    from key_pool import Credential

    monkeypatch.delenv("RUNTIME_ENV_DISABLE_DOTENV", raising=False)

    multimodal = Credential(
        category="embedding",
        provider="catalog",
        api_key="pool-multimodal-key",
        base_url="https://catalog.example/v1/multimodal-embedding",
        model="multimodal-embedding-v1",
        line_no=1,
    )
    text_under_wrong_header = Credential(
        category="rerank",
        provider="catalog",
        api_key="pool-text-key",
        base_url="https://catalog.example/v1/embeddings",
        model="text-embedding-v4",
        line_no=2,
    )

    class FakePool:
        def list(self, category: str) -> list[Credential]:
            if category == "embedding":
                return [multimodal]
            if category == "rerank":
                return [text_under_wrong_header]
            return []

        def first(self, category: str) -> Credential | None:
            items = self.list(category)
            return items[0] if items else None

    monkeypatch.setattr(
        rte,
        "env_value",
        lambda *names, default=None: default,
    )
    monkeypatch.setattr(key_pool, "get_pool", lambda *args, **kwargs: FakePool())

    api_key, base_url, model = rte.resolve_embedding_config(
        default_base_url="https://default.example/v1/embeddings",
        default_model="Qwen/Qwen3-Embedding-8B",
    )

    assert api_key == "pool-text-key"
    assert base_url == "https://catalog.example/v1/embeddings"
    assert model == "text-embedding-v4"


def test_resolver_prefers_grouped_embedding_credential_over_mismatched_flat_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Grouped embedding creds should outrank flat env key/base/model combinations that point at chat gateways."""
    import key_pool
    import runtime_env as rte
    from key_pool import Credential

    monkeypatch.delenv("RUNTIME_ENV_DISABLE_DOTENV", raising=False)

    flat_values = {
        "SILICONFLOW_API_KEY": "flat-answer-key",
        "BASE_URL": "https://chat.example.test/v1",
        "EMBEDDING_MODEL": "multimodal-embedding-v1",
    }

    def fake_env_value(*names: str, default: str | None = None) -> str | None:
        for name in names:
            if name in flat_values:
                return flat_values[name]
        return default

    class FakePool:
        def list(self, category: str) -> list[Credential]:
            if category != "embedding":
                return []
            return [
                Credential(
                    category="embedding",
                    provider="catalog",
                    api_key="pool-text-key",
                    base_url="https://api.siliconflow.cn/v1/embeddings",
                    model="BAAI/bge-m3",
                    line_no=1,
                )
            ]

        def first(self, category: str) -> Credential | None:
            items = self.list(category)
            return items[0] if items else None

    monkeypatch.setattr(rte, "env_value", fake_env_value)
    monkeypatch.setattr(key_pool, "get_pool", lambda *args, **kwargs: FakePool())
    monkeypatch.setattr(rte, "_probe_embedding_key", lambda api_key, *_a, **_kw: api_key == "pool-text-key")

    api_key, base_url, model = rte.resolve_embedding_config(
        default_base_url="https://default.example/v1/embeddings",
        default_model="BAAI/bge-m3",
    )

    assert api_key == "pool-text-key"
    assert base_url == "https://api.siliconflow.cn/v1/embeddings"
    assert model == "BAAI/bge-m3"
