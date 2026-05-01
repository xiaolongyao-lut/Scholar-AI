"""Validity-first embedding key resolution tests.

Mirrors the rerank-side design from
`.claude_squad/decisions/2026-04-24-rerank-key-resolution-redesign.md` §5.1-§5.4
per the 2026-04-25 Morpheus audit §5.2.

The audit DoD items covered here:
  1. explicit api_key bypasses probe
  2. validity-first picks the working key when multiple are present
  3. EMBEDDING_KEY_PROBE_DISABLE=1 restores static behaviour
  4. all-probe-fail → WARN + fallback to first candidate
  5. Gap B closed: RERANK_API_KEY no longer acceptable for embeddings
  6. Gap C closed: no silent /v1/rerank → /v1/embeddings URL rewrite
"""
from __future__ import annotations

import logging

import pytest

import runtime_env as rte


EMBED_ENV_KEYS = (
    "RUNTIME_ENV_DISABLE_DOTENV",
    "SILICONFLOW_API_KEY",
    "SILICONFLOW_EMBEDDING_API_KEY",
    "JINA_API_KEY",
    "EMBEDDING_API_KEY",
    "RERANK_API_KEY",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_KEY_PROBE_DISABLE",
    "SILICONFLOW_EMBEDDING_BASE_URL",
    "EMBEDDING_BASE_URL",
    "BASE_URL",
    "SILICONFLOW_EMBEDDING_MODEL",
    "EMBEDDING_MODEL",
    "MODEL",
)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in EMBED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("RUNTIME_ENV_DISABLE_DOTENV", "1")
    rte._KEY_PROBE_CACHE_EMBED.clear()


def _resolve() -> tuple[str | None, str, str]:
    return rte.resolve_embedding_config(
        default_base_url="https://api.siliconflow.cn/v1/embeddings",
        default_model="Qwen/Qwen3-Embedding-8B",
    )


def test_explicit_key_bypasses_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit caller-passed api_key is authoritative — probe never runs."""
    monkeypatch.setenv("SILICONFLOW_API_KEY", "env-key")
    called = {"n": 0}

    def fake_probe(*_a: object, **_kw: object) -> bool:
        called["n"] += 1
        return False

    monkeypatch.setattr(rte, "_probe_embedding_key", fake_probe)

    key, _base, _model = rte.resolve_embedding_config(
        api_key="caller-supplied-key",
        default_base_url="https://api.siliconflow.cn/v1/embeddings",
        default_model="Qwen/Qwen3-Embedding-8B",
    )

    assert key == "caller-supplied-key"
    assert called["n"] == 0


def test_validity_first_picks_working_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """When multiple SiliconFlow candidates exist, the probed-OK one wins.

    This is the mirror of the rerank fix: SILICONFLOW_API_KEY being present
    first in env order no longer decides the selection; actual 2xx does.
    """
    monkeypatch.setenv("SILICONFLOW_EMBEDDING_API_KEY", "bad-embed-specific")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "good-generic")

    def fake_probe(api_key: str, *_a: object, **_kw: object) -> bool:
        return api_key == "good-generic"

    monkeypatch.setattr(rte, "_probe_embedding_key", fake_probe)

    key, _base, _model = _resolve()
    assert key == "good-generic"


def test_kill_switch_restores_static_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """EMBEDDING_KEY_PROBE_DISABLE=1 → first candidate wins without probing."""
    monkeypatch.setenv("EMBEDDING_KEY_PROBE_DISABLE", "1")
    monkeypatch.setenv("SILICONFLOW_EMBEDDING_API_KEY", "embed-specific")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "generic")
    called = {"n": 0}

    def fake_probe(*_a: object, **_kw: object) -> bool:
        called["n"] += 1
        return True

    monkeypatch.setattr(rte, "_probe_embedding_key", fake_probe)

    key, _base, _model = _resolve()
    # Priority list: SILICONFLOW_EMBEDDING_API_KEY is first.
    assert key == "embed-specific"
    assert called["n"] == 0  # probe never invoked under kill switch


def test_all_probes_fail_warn_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """All-fail → WARN log + fallback to first candidate (legacy shape)."""
    monkeypatch.setenv("SILICONFLOW_EMBEDDING_API_KEY", "dead-specific")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "dead-generic")

    monkeypatch.setattr(rte, "_probe_embedding_key", lambda *a, **k: False)

    with caplog.at_level(logging.WARNING, logger=rte.logger.name):
        key, _base, _model = _resolve()

    assert key == "dead-specific"  # first in priority list
    assert any(
        "All embedding key probes failed" in record.message
        for record in caplog.records
    )


def test_rerank_api_key_not_accepted_for_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gap B: RERANK_API_KEY alone must NOT route to embedding.

    Historical bug mirror — the rerank fix removed SILICONFLOW_API_KEY from
    the rerank candidate list; here we remove RERANK_API_KEY from the
    embedding candidate list.
    """
    monkeypatch.setenv("RERANK_API_KEY", "rerank-only-key")
    # No SILICONFLOW_*, no JINA_*, no EMBEDDING_API_KEY — only rerank key.
    monkeypatch.setenv("EMBEDDING_KEY_PROBE_DISABLE", "1")  # avoid live probe

    key, _base, _model = _resolve()
    assert key is None, (
        "RERANK_API_KEY must not satisfy embedding resolution "
        "(audit Gap B)."
    )


def test_no_url_rewrite_when_rerank_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gap C: /v1/rerank URL must NOT be silently rewritten to /v1/embeddings.

    Under the old resolver a SiliconFlow rerank URL leaked into
    SILICONFLOW_EMBEDDING_BASE_URL would be rewritten. The new resolver
    returns it verbatim; the probe (or first HTTP call downstream) catches
    the misconfiguration loudly instead.
    """
    monkeypatch.setenv("SILICONFLOW_API_KEY", "some-key")
    monkeypatch.setenv(
        "SILICONFLOW_EMBEDDING_BASE_URL",
        "https://api.siliconflow.cn/v1/rerank",
    )
    monkeypatch.setenv("EMBEDDING_KEY_PROBE_DISABLE", "1")

    _key, base_url, _model = _resolve()
    assert base_url == "https://api.siliconflow.cn/v1/rerank"
    assert "embeddings" not in base_url


def test_probe_cached_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """DoD item 6: probe result cached — second resolve issues zero probes.

    We call _probe_embedding_key directly twice with the same args and verify
    the underlying HTTP client (httpx) is invoked at most once.
    """
    monkeypatch.setenv("SILICONFLOW_API_KEY", "some-key")

    calls = {"n": 0}

    class FakeResponse:
        status_code = 200

    class FakeClient:
        def __init__(self, *a: object, **kw: object) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def post(self, *a: object, **kw: object) -> FakeResponse:
            calls["n"] += 1
            return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "Client", FakeClient)

    assert rte._probe_embedding_key(
        "some-key",
        "https://api.siliconflow.cn/v1/embeddings",
        "Qwen/Qwen3-Embedding-8B",
    ) is True
    assert rte._probe_embedding_key(
        "some-key",
        "https://api.siliconflow.cn/v1/embeddings",
        "Qwen/Qwen3-Embedding-8B",
    ) is True
    assert calls["n"] == 1  # second call served from cache


def test_probe_never_logs_raw_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DoD item 5: failed probe logs only length + last 4 chars, never the key."""
    secret = "super-secret-key-abcd1234"

    class FakeResponse:
        status_code = 401

    class FakeClient:
        def __init__(self, *a: object, **kw: object) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def post(self, *a: object, **kw: object) -> FakeResponse:
            return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "Client", FakeClient)

    with caplog.at_level(logging.WARNING, logger=rte.logger.name):
        ok = rte._probe_embedding_key(
            secret,
            "https://api.siliconflow.cn/v1/embeddings",
            "Qwen/Qwen3-Embedding-8B",
        )

    assert ok is False
    joined = " ".join(record.message for record in caplog.records)
    assert secret not in joined
    assert "1234" in joined  # last 4 chars OK
    assert "key_len=" in joined


def test_probe_rejects_http_200_when_payload_is_not_embedding_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Schema-aware probe contract: 2xx + non-embedding payload must be rejected."""

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}

        def json(self) -> dict[str, object]:
            return {"ok": True, "message": "html gateway page"}

    class FakeClient:
        def __init__(self, *a: object, **kw: object) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def post(self, *a: object, **kw: object) -> FakeResponse:
            return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "Client", FakeClient)

    ok = rte._probe_embedding_key(
        "schema-test-key",
        "https://example.test/v1/embeddings",
        "Qwen/Qwen3-Embedding-8B",
    )
    assert ok is False


def test_probe_dashscope_multimodal_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DashScope multimodal embedding probe must use provider-aware URL/payload."""

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {
                "output": {
                    "embeddings": [
                        {"embedding": [0.1, 0.2, 0.3]},
                    ]
                }
            }

    class FakeClient:
        def __init__(self, *a: object, **kw: object) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeResponse:
            assert url == (
                "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
                "multimodal-embedding/multimodal-embedding"
            )
            assert headers["Authorization"] == "Bearer dashscope-key"
            assert json == {
                "model": "multimodal-embedding-v1",
                "input": {"contents": [{"text": "probe"}]},
            }
            return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "Client", FakeClient)

    ok = rte._probe_embedding_key(
        "dashscope-key",
        "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
        "multimodal-embedding/multimodal-embedding",
        "multimodal-embedding-v1",
    )

    assert ok is True
