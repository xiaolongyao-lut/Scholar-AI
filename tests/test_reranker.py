from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest
import reranker_client as rc


@pytest.fixture(autouse=True)
def disable_local_dotenv(monkeypatch):
    monkeypatch.setenv("RUNTIME_ENV_DISABLE_DOTENV", "1")


@pytest.fixture(autouse=True)
def _isolate_rerank_env(monkeypatch):
    """Ensure no live .env rerank keys leak into mocked tests."""
    for var in (
        "RERANK_API_KEY",
        "RERANK_BASE_URL",
        "RERANK_MODEL",
        "DASHSCOPE_RERANK_API_KEY",
        "DASHSCOPE_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def isolated_budget_guard(monkeypatch, tmp_path):
    import model_call_gateway as gateway_mod
    import reranker_client as reranker_mod
    import rerank_cache as rerank_cache_mod

    out_dir = tmp_path / "output"
    out_dir.mkdir()
    monkeypatch.setattr(reranker_mod, "RERANK_BUDGET_STATE_PATH", out_dir / "rerank_budget_state.json", raising=False)
    monkeypatch.setattr(reranker_mod, "RERANK_COST_LOG_PATH", out_dir / "rerank_cost.jsonl", raising=False)
    monkeypatch.setattr(reranker_mod, "_GLOBAL_RERANK_BUDGET_GUARD", None, raising=False)
    monkeypatch.setattr(reranker_mod, "_KEY_PROBE_CACHE", {}, raising=False)
    monkeypatch.setenv("RERANK_DISK_CACHE_DIR", "0")
    monkeypatch.setenv("RERANK_DAILY_CALL_CAP", "5000")
    monkeypatch.setenv("RERANK_DAILY_BUDGET_USD", "5")
    monkeypatch.setenv("MODEL_CALL_GATEWAY_CACHE_DIR", str(out_dir / "model_gateway_cache"))
    monkeypatch.setenv("MODEL_CALL_GATEWAY_METRICS_PATH", str(out_dir / "gateway_metrics.jsonl"))
    rerank_cache_mod._GLOBAL_RERANK_CACHE._store.clear()
    rerank_cache_mod._GLOBAL_RERANK_CACHE._disk_dir = None
    for name in ("_SEMAPHORE_RERANK", "_SEMAPHORE_EMBEDDING", "_SEMAPHORE_LLM"):
        if hasattr(gateway_mod, name):
            monkeypatch.delattr(gateway_mod, name, raising=False)


def _read_gateway_metrics(out_dir) -> list[dict]:
    path = out_dir / "gateway_metrics.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class _StubResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


class _StubAsyncClient:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        assert url == "https://api.siliconflow.cn/v1/rerank"
        assert json["model"] == "qwen3-rerank"
        assert json["query"] == "laser query"
        assert len(json["documents"]) == 3
        return _StubResponse(
            status_code=200,
            payload={
                "results": [
                    {"index": 1, "relevance_score": 0.95},
                    {"index": 0, "relevance_score": 0.12},
                    {"index": 2, "relevance_score": 0.01},
                ]
            },
        )


class _StubAsyncClient429Then200:
    calls = 0

    def __init__(self, *_args, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, _url, headers=None, json=None):
        _ = headers, json
        _StubAsyncClient429Then200.calls += 1
        if _StubAsyncClient429Then200.calls == 1:
            return _StubResponse(status_code=429, payload={"error": "rate limited"})
        return _StubResponse(
            status_code=200,
            payload={
                "results": [
                    {"index": 2, "relevance_score": 0.99},
                    {"index": 0, "relevance_score": 0.50},
                    {"index": 1, "relevance_score": 0.10},
                ]
            },
        )


class _DashScopeStubAsyncClient:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        assert url == "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
        assert headers["Authorization"] == "Bearer dashscope_key"
        assert json["model"] == "qwen3-rerank"
        assert json["input"]["query"] == "laser query"
        assert json["input"]["documents"] == ["doc A", "doc B"]
        assert json["parameters"]["top_n"] == 2
        assert json["parameters"]["return_documents"] is False
        return _StubResponse(
            status_code=200,
            payload={
                "output": {
                    "results": [
                        {"index": 1, "relevance_score": 0.91},
                        {"index": 0, "relevance_score": 0.33},
                    ]
                }
            },
        )


def test_rerank_preserves_order_without_api_key(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("SILICONFLOW_RERANK_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_RERANK_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("RERANK_API_KEY", raising=False)
    monkeypatch.setenv("RERANK_KEY_PROBE_DISABLE", "1")
    from reranker_client import rerank

    candidates = [
        {"chunk_id": "c1", "content": "完全无关的天气预报内容", "rrf_score": 0.9},
        {"chunk_id": "c2", "content": "海洋生物泵是碳循环的核心驱动力", "rrf_score": 0.8},
        {"chunk_id": "c3", "content": "随机噪音文本", "rrf_score": 0.7},
    ]

    result = rerank("海洋碳循环的主要机制", candidates, api_key=None)

    assert [item["chunk_id"] for item in result] == ["c1", "c2", "c3"]
    assert all("rerank_score" in item for item in result)
    assert result[0]["rerank_score"] == candidates[0]["rrf_score"]


def test_rerank_respects_top_k_without_api_key(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("SILICONFLOW_RERANK_API_KEY", raising=False)
    from reranker_client import rerank

    candidates = [{"chunk_id": f"c{i}", "content": f"text {i}", "rrf_score": 1.0 / (i + 1)} for i in range(20)]
    result = rerank("query", candidates, top_k=5, api_key=None)
    assert len(result) == 5
    assert result[0]["chunk_id"] == "c0"


def test_rerank_handles_empty_candidates():
    from reranker_client import rerank

    assert rerank("query", [], api_key=None) == []


def test_resolve_rerank_config_prefers_provider_specific_values_over_legacy_generic_env(monkeypatch):
    monkeypatch.setenv("RERANK_API_KEY", "legacy_key")
    monkeypatch.setenv("RERANK_BASE_URL", "https://api.siliconflow.cn/v1/rerank")
    monkeypatch.setenv("RERANK_MODEL", "netease-youdao/bce-reranker-base_v1")
    monkeypatch.setenv("SILICONFLOW_RERANK_API_KEY", "sf_key")
    monkeypatch.setenv("SILICONFLOW_RERANK_BASE_URL", "https://api.siliconflow.cn/v1/rerank")
    monkeypatch.delenv("SILICONFLOW_RERANK_MODEL", raising=False)
    monkeypatch.delenv("DASHSCOPE_RERANK_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_RERANK_BASE_URL", raising=False)
    monkeypatch.delenv("DASHSCOPE_RERANK_MODEL", raising=False)

    from reranker_client import resolve_rerank_config

    api_key, base_url, model = resolve_rerank_config()

    assert api_key == "sf_key"
    assert base_url == "https://api.siliconflow.cn/v1/rerank"
    assert model == "qwen3-rerank"


def test_explicit_key_bypasses_probe(monkeypatch):
    monkeypatch.setenv("SILICONFLOW_API_KEY", "bad")
    monkeypatch.setenv("RERANK_API_KEY", "also-bad")
    called = {"n": 0}

    def fake_probe(*_args, **_kwargs):
        called["n"] += 1
        return False

    monkeypatch.setattr(rc, "_probe_rerank_key", fake_probe)

    key, *_ = rc.resolve_rerank_config(api_key="caller-key")

    assert key == "caller-key"
    assert called["n"] == 0


def test_validity_first_picks_working_key(monkeypatch):
    monkeypatch.setenv("SILICONFLOW_API_KEY", "bad-38-char")
    monkeypatch.setenv("RERANK_API_KEY", "good-51-char")
    monkeypatch.delenv("SILICONFLOW_RERANK_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_RERANK_API_KEY", raising=False)

    monkeypatch.setattr(rc, "_probe_rerank_key", lambda key, *_args, **_kwargs: key == "good-51-char")

    key, *_ = rc.resolve_rerank_config()

    assert key == "good-51-char"


def test_kill_switch_restores_static_order(monkeypatch):
    monkeypatch.setenv("RERANK_KEY_PROBE_DISABLE", "1")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "bad")
    monkeypatch.setenv("RERANK_API_KEY", "good")
    called = {"n": 0}

    def fake_probe(*_args, **_kwargs):
        called["n"] += 1
        return True

    monkeypatch.setattr(rc, "_probe_rerank_key", fake_probe)

    key, *_ = rc.resolve_rerank_config()

    assert key == "bad"
    assert called["n"] == 0


def test_all_probes_fail_fallback(monkeypatch, caplog):
    monkeypatch.setenv("SILICONFLOW_API_KEY", "bad")
    monkeypatch.delenv("RERANK_KEY_PROBE_DISABLE", raising=False)
    monkeypatch.setattr(rc, "_probe_rerank_key", lambda *_args, **_kwargs: False)

    with caplog.at_level(logging.WARNING):
        key, *_ = rc.resolve_rerank_config()

    assert key == "bad"
    assert any("All rerank key probes failed" in record.message for record in caplog.records)


def test_all_probes_fail_uses_static_provider_key_semantics(monkeypatch, caplog):
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-bad")
    monkeypatch.setenv("RERANK_API_KEY", "legacy-bad")
    monkeypatch.delenv("SILICONFLOW_RERANK_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_RERANK_API_KEY", raising=False)
    monkeypatch.delenv("RERANK_KEY_PROBE_DISABLE", raising=False)
    probed_keys: list[str] = []

    def fake_probe(key, *_args, **_kwargs):
        probed_keys.append(key)
        return False

    monkeypatch.setattr(rc, "_probe_rerank_key", fake_probe)

    with caplog.at_level(logging.WARNING):
        key, *_ = rc.resolve_rerank_config()

    assert probed_keys == ["legacy-bad", "sf-bad"]
    assert key == "sf-bad"
    assert any("source=siliconflow-generic" in record.message for record in caplog.records)


def test_probe_reject_falls_back_to_alternate_provider_key(monkeypatch):
    """R1.1 (substitute): resolver has no Jina path, but the same validity-first
    semantic applies across provider keys — if the 38-char SiliconFlow key is
    rejected by the probe, resolver must advance to the next valid candidate
    (here: DASHSCOPE_RERANK_API_KEY) rather than returning the rejected key.
    """
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-bad-38char")
    monkeypatch.setenv("DASHSCOPE_RERANK_API_KEY", "ds-good")
    monkeypatch.delenv("SILICONFLOW_RERANK_API_KEY", raising=False)
    monkeypatch.delenv("RERANK_API_KEY", raising=False)
    monkeypatch.delenv("RERANK_KEY_PROBE_DISABLE", raising=False)

    def fake_probe(key, *_args, **_kwargs):
        return key == "ds-good"

    monkeypatch.setattr(rc, "_probe_rerank_key", fake_probe)

    key, _base_url, _model = rc.resolve_rerank_config()

    assert key == "ds-good"


def test_resolve_rerank_config_uses_key_pool_pairs_from_dotenv(monkeypatch, tmp_path):
    import key_pool as key_pool_mod
    import runtime_env as runtime_env_mod

    monkeypatch.delenv("RUNTIME_ENV_DISABLE_DOTENV", raising=False)
    for name in (
        "SILICONFLOW_API_KEY",
        "SILICONFLOW_RERANK_API_KEY",
        "SILICONFLOW_RERANK_BASE_URL",
        "SILICONFLOW_RERANK_MODEL",
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_RERANK_API_KEY",
        "DASHSCOPE_RERANK_BASE_URL",
        "DASHSCOPE_RERANK_MODEL",
        "RERANK_API_KEY",
        "RERANK_BASE_URL",
        "RERANK_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)

    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "##rerank##",
                "API_KEY=bad-key",
                "BASE_URL=https://api.siliconflow.cn/v1/rerank",
                "MODEL=BAAI/bge-reranker-v2-m3",
                "API_KEY=good-key",
                "BASE_URL=https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
                "MODEL=qwen3-rerank",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    runtime_env_mod._repo_env.cache_clear()
    monkeypatch.setattr(key_pool_mod, "_singleton", None, raising=False)
    monkeypatch.setattr(key_pool_mod, "_singleton_path", None, raising=False)
    monkeypatch.setattr(rc, "_KEY_PROBE_CACHE", {}, raising=False)
    monkeypatch.setattr(rc, "_RERANK_CREDENTIAL_COOLDOWN", {}, raising=False)
    monkeypatch.setattr(
        rc,
        "_probe_rerank_key",
        lambda key, *_args, **_kwargs: key == "good-key",
    )

    key, base_url, model = rc.resolve_rerank_config()

    assert key == "good-key"
    assert base_url == "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    assert model == "qwen3-rerank"


def test_resolve_rerank_config_sanitizes_nested_env_assignment_in_url(monkeypatch, tmp_path):
    import key_pool as key_pool_mod
    import runtime_env as runtime_env_mod

    monkeypatch.delenv("RUNTIME_ENV_DISABLE_DOTENV", raising=False)
    monkeypatch.delenv("RERANK_KEY_PROBE_DISABLE", raising=False)
    for name in (
        "SILICONFLOW_API_KEY",
        "SILICONFLOW_RERANK_API_KEY",
        "SILICONFLOW_RERANK_BASE_URL",
        "SILICONFLOW_RERANK_MODEL",
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_RERANK_API_KEY",
        "DASHSCOPE_RERANK_BASE_URL",
        "DASHSCOPE_RERANK_MODEL",
        "RERANK_API_KEY",
        "RERANK_BASE_URL",
        "RERANK_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)

    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "##rerank##",
                "RERANK_API_KEY=rerank-good-key",
                "RERANK_BASE_URL=OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1",
                "RERANK_MODEL=qwen3-rerank",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    runtime_env_mod._repo_env.cache_clear()
    monkeypatch.setattr(key_pool_mod, "_singleton", None, raising=False)
    monkeypatch.setattr(key_pool_mod, "_singleton_path", None, raising=False)
    monkeypatch.setattr(rc, "_KEY_PROBE_CACHE", {}, raising=False)
    monkeypatch.setattr(rc, "_RERANK_CREDENTIAL_COOLDOWN", {}, raising=False)

    expected_url = rc.DEFAULT_DASHSCOPE_RERANKER_URL
    probed: list[tuple[str, str, str]] = []

    def fake_probe(api_key: str, base_url: str, model: str, **_kwargs: object) -> bool:
        probed.append((api_key, base_url, model))
        return base_url == expected_url

    monkeypatch.setattr(rc, "_probe_rerank_key", fake_probe)

    key, base_url, model = rc.resolve_rerank_config()

    assert probed == [("rerank-good-key", expected_url, "qwen3-rerank")]
    assert key == "rerank-good-key"
    assert base_url == expected_url
    assert model == "qwen3-rerank"


def test_resolve_rerank_config_normalizes_dashscope_compatible_mode_url(monkeypatch):
    monkeypatch.setenv("RERANK_API_KEY", "rerank-good-key")
    monkeypatch.setenv("RERANK_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("RERANK_MODEL", "qwen3-vl-rerank")
    monkeypatch.delenv("RERANK_KEY_PROBE_DISABLE", raising=False)

    probed: list[tuple[str, str, str]] = []

    def fake_probe(api_key: str, base_url: str, model: str, **_kwargs: object) -> bool:
        probed.append((api_key, base_url, model))
        return base_url == rc.DEFAULT_DASHSCOPE_RERANKER_URL

    monkeypatch.setattr(rc, "_probe_rerank_key", fake_probe)

    key, base_url, model = rc.resolve_rerank_config()

    assert probed == [(
        "rerank-good-key",
        rc.DEFAULT_DASHSCOPE_RERANKER_URL,
        "qwen3-vl-rerank",
    )]
    assert key == "rerank-good-key"
    assert base_url == rc.DEFAULT_DASHSCOPE_RERANKER_URL
    assert model == "qwen3-vl-rerank"


def test_rerank_async_fails_over_to_next_key_pool_credential(monkeypatch, tmp_path):
    import key_pool as key_pool_mod
    import runtime_env as runtime_env_mod
    import reranker_client as reranker_mod

    monkeypatch.delenv("RUNTIME_ENV_DISABLE_DOTENV", raising=False)
    for name in (
        "SILICONFLOW_API_KEY",
        "SILICONFLOW_RERANK_API_KEY",
        "SILICONFLOW_RERANK_BASE_URL",
        "SILICONFLOW_RERANK_MODEL",
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_RERANK_API_KEY",
        "DASHSCOPE_RERANK_BASE_URL",
        "DASHSCOPE_RERANK_MODEL",
        "RERANK_API_KEY",
        "RERANK_BASE_URL",
        "RERANK_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)

    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "##rerank##",
                "API_KEY=bad-key",
                "BASE_URL=https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
                "MODEL=qwen3-rerank",
                "API_KEY=good-key",
                "BASE_URL=https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
                "MODEL=qwen3-rerank",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    runtime_env_mod._repo_env.cache_clear()
    monkeypatch.setattr(key_pool_mod, "_singleton", None, raising=False)
    monkeypatch.setattr(key_pool_mod, "_singleton_path", None, raising=False)
    monkeypatch.setattr(reranker_mod, "_KEY_PROBE_CACHE", {}, raising=False)
    monkeypatch.setattr(reranker_mod, "_RERANK_CREDENTIAL_COOLDOWN", {}, raising=False)
    monkeypatch.setenv("RERANK_CACHE_ENABLED", "0")
    monkeypatch.setattr(reranker_mod, "_probe_rerank_key", lambda *_args, **_kwargs: True)

    class _FailoverAsyncClient:
        calls: list[str] = []

        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            _ = json
            _FailoverAsyncClient.calls.append(headers["Authorization"])
            assert url == "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
            if headers["Authorization"] == "Bearer bad-key":
                return _StubResponse(status_code=401, payload={"error": "unauthorized"})
            return _StubResponse(
                status_code=200,
                payload={
                    "output": {
                        "results": [
                            {"index": 1, "relevance_score": 0.92},
                            {"index": 0, "relevance_score": 0.21},
                        ]
                    }
                },
            )

    monkeypatch.setattr(reranker_mod.httpx, "AsyncClient", _FailoverAsyncClient)

    candidates = [
        {"chunk_id": "c1", "content": "doc A", "rrf_score": 0.8},
        {"chunk_id": "c2", "content": "doc B", "rrf_score": 0.7},
    ]

    reranked = asyncio.run(reranker_mod.rerank_async("laser query", candidates, top_k=2))

    assert _FailoverAsyncClient.calls == ["Bearer bad-key", "Bearer good-key"]
    assert [item["chunk_id"] for item in reranked] == ["c2", "c1"]
    assert reranked[0]["rerank_model"] == "qwen3-rerank"
    assert reranked[0]["rerank_source"] == "key-pool:unknown"


def test_probe_rerank_key_caches_successful_result(monkeypatch):
    calls = {"n": 0}

    class _ProbeResponse:
        status_code = 200

    class _ProbeClient:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers=None, json=None):
            calls["n"] += 1
            assert url == "https://api.siliconflow.cn/v1/rerank"
            assert headers["Authorization"] == "Bearer probe-key-1234"
            assert json == {
                "model": "qwen3-rerank",
                "query": "probe",
                "documents": ["probe"],
                "top_n": 1,
            }
            return _ProbeResponse()

    monkeypatch.setattr(rc, "_KEY_PROBE_CACHE", {})
    monkeypatch.setattr(rc.httpx, "Client", _ProbeClient)

    assert rc._probe_rerank_key("probe-key-1234", "https://api.siliconflow.cn/v1/rerank", "qwen3-rerank") is True
    assert rc._probe_rerank_key("probe-key-1234", "https://api.siliconflow.cn/v1/rerank", "qwen3-rerank") is True
    assert calls["n"] == 1


def test_probe_rerank_key_uses_dashscope_payload(monkeypatch):
    calls = {"n": 0}

    class _ProbeResponse:
        status_code = 200

    class _ProbeClient:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers=None, json=None):
            calls["n"] += 1
            assert url == "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
            assert headers["Authorization"] == "Bearer probe-key-1234"
            assert json == {
                "model": "qwen3-rerank",
                "input": {"query": "probe", "documents": ["probe"]},
                "parameters": {"top_n": 1, "return_documents": False},
            }
            return _ProbeResponse()

    monkeypatch.setattr(rc, "_KEY_PROBE_CACHE", {})
    monkeypatch.setattr(rc.httpx, "Client", _ProbeClient)

    assert (
        rc._probe_rerank_key(
            "probe-key-1234",
            "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
            "qwen3-rerank",
        )
        is True
    )
    assert calls["n"] == 1


def test_probe_rerank_key_logs_redacted_failure(monkeypatch, caplog):
    class _ProbeResponse:
        status_code = 401

    class _ProbeClient:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers=None, json=None):
            _ = url, headers, json
            return _ProbeResponse()

    monkeypatch.setattr(rc, "_KEY_PROBE_CACHE", {})
    monkeypatch.setattr(rc.httpx, "Client", _ProbeClient)

    with caplog.at_level(logging.WARNING):
        ok = rc._probe_rerank_key("secret-probe-1234", "https://api.siliconflow.cn/v1/rerank", "qwen3-rerank")

    assert ok is False
    assert "secret-probe-1234" not in caplog.text
    assert "key_len=17" in caplog.text
    assert "key_suffix=***1234" in caplog.text


def test_rerank_async_reorders_using_api(monkeypatch):
    import reranker_client as reranker_mod

    monkeypatch.setattr(reranker_mod.httpx, "AsyncClient", _StubAsyncClient)
    monkeypatch.delenv("SILICONFLOW_RERANK_BASE_URL", raising=False)
    monkeypatch.delenv("SILICONFLOW_RERANK_MODEL", raising=False)
    monkeypatch.delenv("DASHSCOPE_RERANK_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("RERANK_API_KEY", raising=False)
    monkeypatch.delenv("RERANK_BASE_URL", raising=False)
    monkeypatch.delenv("RERANK_MODEL", raising=False)

    candidates = [
        {"chunk_id": "c1", "content": "doc A", "rrf_score": 0.8},
        {"chunk_id": "c2", "content": "doc B", "rrf_score": 0.7},
        {"chunk_id": "c3", "content": "doc C", "rrf_score": 0.6},
    ]

    reranked = asyncio.run(reranker_mod.rerank_async("laser query", candidates, api_key="sf_key"))

    assert [item["chunk_id"] for item in reranked] == ["c2", "c1", "c3"]
    assert reranked[0]["rerank_score"] == 0.95
    assert reranked[1]["rerank_score"] == 0.12


def test_rerank_async_uses_dashscope_qwen3_text_mode_by_default(monkeypatch):
    import reranker_client as reranker_mod

    monkeypatch.setattr(reranker_mod.httpx, "AsyncClient", _DashScopeStubAsyncClient)
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("SILICONFLOW_RERANK_API_KEY", raising=False)
    monkeypatch.delenv("SILICONFLOW_RERANK_BASE_URL", raising=False)
    monkeypatch.delenv("SILICONFLOW_RERANK_MODEL", raising=False)
    monkeypatch.delenv("DASHSCOPE_RERANK_BASE_URL", raising=False)
    monkeypatch.delenv("DASHSCOPE_RERANK_MODEL", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope_key")

    candidates = [
        {"chunk_id": "c1", "content": "doc A", "rrf_score": 0.8},
        {"chunk_id": "c2", "content": "doc B", "rrf_score": 0.7},
    ]

    reranked = asyncio.run(reranker_mod.rerank_async("laser query", candidates))

    assert [item["chunk_id"] for item in reranked] == ["c2", "c1"]
    assert reranked[0]["rerank_score"] == 0.91


def test_rerank_async_retries_429_then_succeeds(monkeypatch):
    import model_call_gateway as gateway_mod
    import reranker_client as reranker_mod

    _StubAsyncClient429Then200.calls = 0
    monkeypatch.setattr(reranker_mod.httpx, "AsyncClient", _StubAsyncClient429Then200)
    monkeypatch.delenv("SILICONFLOW_RERANK_BASE_URL", raising=False)
    monkeypatch.delenv("SILICONFLOW_RERANK_MODEL", raising=False)
    monkeypatch.setenv("RERANK_CACHE_ENABLED", "0")

    # eliminate actual sleep/jitter delay in unit test
    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(reranker_mod.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(reranker_mod.random, "uniform", lambda _a, _b: 0.0)
    monkeypatch.setattr(gateway_mod.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(gateway_mod.random, "uniform", lambda _a, _b: 0.0)

    candidates = [
        {"chunk_id": "c1", "content": "doc A", "rrf_score": 0.8},
        {"chunk_id": "c2", "content": "doc B", "rrf_score": 0.7},
        {"chunk_id": "c3", "content": "doc C", "rrf_score": 0.6},
    ]
    timings: dict[str, float] = {}

    reranked = asyncio.run(
        reranker_mod.rerank_async("laser query", candidates, api_key="sf_key", timings=timings)
    )

    assert _StubAsyncClient429Then200.calls == 2
    assert timings.get("attempts") == 2
    assert [item["chunk_id"] for item in reranked] == ["c3", "c1", "c2"]
    metrics = _read_gateway_metrics(reranker_mod.RERANK_COST_LOG_PATH.parent)
    assert metrics[-1]["kind"] == "rerank"
    assert metrics[-1]["retry_count"] == 1


def test_parse_retry_after_prefers_ms_header():
    from reranker_client import _parse_retry_after

    assert _parse_retry_after({"retry-after-ms": "1500"}) == 1.5
    assert _parse_retry_after({"retry-after": "3"}) == 3.0
    assert _parse_retry_after({"retry-after-ms": "bogus", "retry-after": "2"}) == 2.0
    assert _parse_retry_after({}) is None
    assert _parse_retry_after(None) is None
    # caps oversized values at MAX_BACKOFF_SECONDS (60s)
    assert _parse_retry_after({"retry-after": "999"}) == 60.0


def test_rerank_async_honors_retry_after_header(monkeypatch):
    """When server returns Retry-After, backoff must use that value (not exponential)."""
    import model_call_gateway as gateway_mod
    import reranker_client as reranker_mod

    captured_sleeps: list[float] = []

    class _RetryAfterStub:
        calls = 0

        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, *_a, **_kw):
            _RetryAfterStub.calls += 1
            if _RetryAfterStub.calls == 1:
                resp = _StubResponse(status_code=429, payload={"error": "rate limited"})
                resp.headers = {"retry-after-ms": "750"}
                return resp
            return _StubResponse(
                status_code=200,
                payload={"results": [{"index": 0, "relevance_score": 0.9}]},
            )

    async def _capture_sleep(seconds):
        captured_sleeps.append(seconds)

    monkeypatch.setattr(reranker_mod.httpx, "AsyncClient", _RetryAfterStub)
    monkeypatch.setattr(reranker_mod.asyncio, "sleep", _capture_sleep)
    monkeypatch.setattr(gateway_mod.random, "uniform", lambda _a, _b: 0.0)
    monkeypatch.setattr(reranker_mod.random, "uniform", lambda _a, _b: 0.0)

    # Disable provider min-interval pacing for this test: we are verifying the
    # Retry-After backoff path, not pacing. Without this the pacer's
    # asyncio.sleep calls would also be captured into `captured_sleeps`.
    async def _noop_pacer(*_a, **_kw):
        return 0.0

    monkeypatch.setattr(
        reranker_mod.provider_rate_limit,
        "maybe_wait_for_rate_limit_async",
        _noop_pacer,
    )

    # Two candidates so the single-candidate short-circuit (A11.R4.1) does
    # not bypass the retry path we are exercising here.
    candidates = [
        {"chunk_id": "c1", "content": "doc A", "rrf_score": 0.5},
        {"chunk_id": "c2", "content": "doc B", "rrf_score": 0.4},
    ]
    asyncio.run(reranker_mod.rerank_async("q", candidates, api_key="sf_key"))

    assert _RetryAfterStub.calls == 2
    assert captured_sleeps == [0.75]  # Retry-After header honored, not 0.5*2^0 exponential


def test_rerank_async_uses_cache_on_repeated_same_request(monkeypatch):
    import reranker_client as reranker_mod

    class _CountStub:
        calls = 0

        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, _url, headers=None, json=None):
            _ = headers, json
            _CountStub.calls += 1
            return _StubResponse(
                status_code=200,
                payload={
                    "results": [
                        {"index": 1, "relevance_score": 0.9},
                        {"index": 0, "relevance_score": 0.1},
                    ]
                },
            )

    monkeypatch.setattr(reranker_mod.httpx, "AsyncClient", _CountStub)
    monkeypatch.delenv("SILICONFLOW_RERANK_BASE_URL", raising=False)
    monkeypatch.delenv("SILICONFLOW_RERANK_MODEL", raising=False)
    monkeypatch.setenv("RERANK_CACHE_ENABLED", "1")
    monkeypatch.setenv("RERANK_CACHE_VERSION", "test-cache-hit")

    candidates = [
        {"chunk_id": "c1", "content": "doc A", "rrf_score": 0.8},
        {"chunk_id": "c2", "content": "doc B", "rrf_score": 0.7},
    ]

    first = asyncio.run(reranker_mod.rerank_async("same query", candidates, api_key="sf_key"))
    second = asyncio.run(reranker_mod.rerank_async("same query", candidates, api_key="sf_key"))

    assert _CountStub.calls == 1
    assert [x["chunk_id"] for x in first] == ["c2", "c1"]
    assert [x["chunk_id"] for x in second] == ["c2", "c1"]
    metrics = _read_gateway_metrics(reranker_mod.RERANK_COST_LOG_PATH.parent)
    assert [row["cache_status"] for row in metrics[-2:]] == ["miss", "hit"]
    assert [row["decision"] for row in metrics[-2:]] == ["invoke", "cache_hit"]


def test_rerank_async_cache_hit_does_not_wait_for_caller_semaphore(monkeypatch):
    import reranker_client as reranker_mod

    class _CountStub:
        calls = 0

        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, _url, headers=None, json=None):
            _ = headers, json
            _CountStub.calls += 1
            return _StubResponse(
                status_code=200,
                payload={
                    "results": [
                        {"index": 1, "relevance_score": 0.9},
                        {"index": 0, "relevance_score": 0.1},
                    ]
                },
            )

    monkeypatch.setattr(reranker_mod.httpx, "AsyncClient", _CountStub)
    monkeypatch.delenv("SILICONFLOW_RERANK_BASE_URL", raising=False)
    monkeypatch.delenv("SILICONFLOW_RERANK_MODEL", raising=False)
    monkeypatch.setenv("RERANK_CACHE_ENABLED", "1")
    monkeypatch.setenv("RERANK_CACHE_VERSION", "test-cache-hit-before-semaphore")

    candidates = [
        {"chunk_id": "c1", "content": "doc A", "rrf_score": 0.8},
        {"chunk_id": "c2", "content": "doc B", "rrf_score": 0.7},
    ]

    async def _scenario():
        semaphore = asyncio.Semaphore(1)
        first = await reranker_mod.rerank_async(
            "same query", candidates, api_key="sf_key", semaphore=semaphore
        )
        await semaphore.acquire()
        timings: dict[str, float] = {}
        try:
            second = await asyncio.wait_for(
                reranker_mod.rerank_async(
                    "same query",
                    candidates,
                    api_key="sf_key",
                    semaphore=semaphore,
                    timings=timings,
                ),
                timeout=0.1,
            )
        finally:
            semaphore.release()
        return first, second, timings

    first, second, timings = asyncio.run(_scenario())

    assert _CountStub.calls == 1
    assert [x["chunk_id"] for x in first] == ["c2", "c1"]
    assert [x["chunk_id"] for x in second] == ["c2", "c1"]
    assert timings["queue_wait_ms"] == 0.0
    assert timings["api_ms"] == 0.0
    assert timings["attempts"] == 0


def test_rerank_async_cache_miss_when_corpus_version_changes(monkeypatch):
    import reranker_client as reranker_mod

    class _CorpusAwareStub:
        calls = 0

        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, _url, headers=None, json=None):
            _ = headers, json
            _CorpusAwareStub.calls += 1
            if _CorpusAwareStub.calls == 1:
                results = [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.1},
                ]
            else:
                results = [
                    {"index": 0, "relevance_score": 0.95},
                    {"index": 1, "relevance_score": 0.05},
                ]
            return _StubResponse(status_code=200, payload={"results": results})

    monkeypatch.setattr(reranker_mod.httpx, "AsyncClient", _CorpusAwareStub)
    monkeypatch.delenv("SILICONFLOW_RERANK_BASE_URL", raising=False)
    monkeypatch.delenv("SILICONFLOW_RERANK_MODEL", raising=False)
    monkeypatch.setenv("RERANK_CACHE_ENABLED", "1")

    base_candidates = [
        {"chunk_id": "c1", "content": "doc A", "rrf_score": 0.8},
        {"chunk_id": "c2", "content": "doc B", "rrf_score": 0.7},
    ]
    first = asyncio.run(
        reranker_mod.rerank_async(
            "same query",
            [{**item, "corpus_version": "corpus-a"} for item in base_candidates],
            api_key="sf_key",
        )
    )
    second = asyncio.run(
        reranker_mod.rerank_async(
            "same query",
            [{**item, "corpus_version": "corpus-b"} for item in base_candidates],
            api_key="sf_key",
        )
    )

    assert _CorpusAwareStub.calls == 2
    assert [x["chunk_id"] for x in first] == ["c2", "c1"]
    assert [x["chunk_id"] for x in second] == ["c1", "c2"]


def test_rerank_async_reuses_async_client_within_same_event_loop(monkeypatch):
    import importlib
    import reranker_client as reranker_mod

    reranker_mod = importlib.reload(reranker_mod)

    class _ReuseStub:
        init_calls = 0
        post_calls = 0

        def __init__(self, *_a, **_kw):
            _ReuseStub.init_calls += 1

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, _url, headers=None, json=None):
            _ = headers, json
            _ReuseStub.post_calls += 1
            return _StubResponse(
                status_code=200,
                payload={
                    "results": [
                        {"index": 1, "relevance_score": 0.9},
                        {"index": 0, "relevance_score": 0.1},
                    ]
                },
            )

    monkeypatch.setattr(reranker_mod.httpx, "AsyncClient", _ReuseStub)
    monkeypatch.setenv("RERANK_CACHE_ENABLED", "0")
    monkeypatch.setenv("RERANK_SHORT_CIRCUIT_SCORE_GAP", "0")
    monkeypatch.setenv("RERANK_KEY_PROBE_DISABLE", "1")
    monkeypatch.setenv("RERANK_DISABLE_BUDGET", "1")
    monkeypatch.delenv("SILICONFLOW_RERANK_BASE_URL", raising=False)
    monkeypatch.delenv("SILICONFLOW_RERANK_MODEL", raising=False)

    candidates = [
        {"chunk_id": "c1", "content": "doc A", "rrf_score": 0.5},
        {"chunk_id": "c2", "content": "doc B", "rrf_score": 0.5},
    ]

    async def _scenario():
        first = await reranker_mod.rerank_async("query-one", candidates, api_key="sf_key")
        second = await reranker_mod.rerank_async("query-two", candidates, api_key="sf_key")
        return first, second

    first, second = asyncio.run(_scenario())

    assert [x["chunk_id"] for x in first] == ["c2", "c1"]
    assert [x["chunk_id"] for x in second] == ["c2", "c1"]
    assert _ReuseStub.post_calls == 2
    assert _ReuseStub.init_calls == 1


def test_warm_rerank_live_candidate_is_one_shot(monkeypatch):
    import importlib
    import reranker_client as reranker_mod

    reranker_mod = importlib.reload(reranker_mod)
    monkeypatch.setattr(reranker_mod, "_RERANK_WARMED_CANDIDATES", set(), raising=False)

    class _WarmStub:
        calls = 0

        def __init__(self, *_a, **_kw):
            pass

        async def post(self, url, headers=None, json=None):
            _WarmStub.calls += 1
            assert url == "https://api.siliconflow.cn/v1/rerank"
            assert headers["Authorization"] == "Bearer sf_key"
            assert json == {
                "model": "qwen3-rerank",
                "query": "warmup",
                "documents": ["warmup"],
                "top_n": 1,
                "return_documents": False,
            }
            return _StubResponse(
                status_code=200,
                payload={"results": [{"index": 0, "relevance_score": 1.0}]},
            )

    monkeypatch.setattr(reranker_mod.httpx, "AsyncClient", _WarmStub)
    monkeypatch.delenv("SILICONFLOW_RERANK_BASE_URL", raising=False)
    monkeypatch.delenv("SILICONFLOW_RERANK_MODEL", raising=False)

    first = asyncio.run(reranker_mod.warm_rerank_live_candidate(api_key="sf_key"))
    second = asyncio.run(reranker_mod.warm_rerank_live_candidate(api_key="sf_key"))

    assert _WarmStub.calls == 1
    assert first["warmed"] is True
    assert second["warmed"] is False
    assert second["reason"] == "already_warmed"


def test_rerank_async_truncates_oversized_documents(monkeypatch):
    """Docs exceeding SAFE_RERANK_DOC_TOKENS must be head-truncated before the POST."""
    import reranker_client as reranker_mod
    from reranker_client import SAFE_RERANK_DOC_TOKENS
    from token_utils import count_tokens

    captured_payloads: list[dict] = []

    class _CapturingStub:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, _url, headers=None, json=None):
            captured_payloads.append(json)
            return _StubResponse(
                status_code=200,
                payload={"results": [
                    {"index": 0, "relevance_score": 0.5},
                    {"index": 1, "relevance_score": 0.3},
                ]},
            )

    monkeypatch.setattr(reranker_mod.httpx, "AsyncClient", _CapturingStub)
    monkeypatch.delenv("SILICONFLOW_RERANK_BASE_URL", raising=False)
    monkeypatch.delenv("SILICONFLOW_RERANK_MODEL", raising=False)
    monkeypatch.setenv("CHUNK_HARD_MAX_CHARS", "999999")
    monkeypatch.setenv("CHUNK_HARD_MAX_TOKENS", "999999")

    long_doc = "激光焊接钛合金。" * 5000  # well above 7500 tokens
    short_doc = "微观组织演化"
    candidates = [
        {"chunk_id": "big", "content": long_doc, "rrf_score": 0.9},
        {"chunk_id": "small", "content": short_doc, "rrf_score": 0.8},
    ]

    reranked = asyncio.run(reranker_mod.rerank_async("q", candidates, api_key="sf_key"))

    assert len(captured_payloads) == 1
    sent_docs = captured_payloads[0]["documents"]
    assert len(sent_docs) == 2
    assert count_tokens(sent_docs[0]) <= SAFE_RERANK_DOC_TOKENS
    assert sent_docs[1] == short_doc  # untouched
    # Reranked output still keys back to original candidates
    assert {item["chunk_id"] for item in reranked} == {"big", "small"}


def test_rerank_async_skips_oversize_candidates_before_http(monkeypatch):
    import reranker_client as reranker_mod

    class _NeverCalledAsyncClient:
        calls = 0

        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, *_a, **_kw):
            _NeverCalledAsyncClient.calls += 1
            return _StubResponse(status_code=200, payload={"results": []})

    logged: list[dict] = []
    monkeypatch.setattr(reranker_mod.httpx, "AsyncClient", _NeverCalledAsyncClient)
    monkeypatch.setattr(reranker_mod, "_rerank_log_call", lambda **kwargs: logged.append(kwargs))
    monkeypatch.setenv("CHUNK_HARD_MAX_CHARS", "100")
    monkeypatch.setenv("CHUNK_HARD_MAX_TOKENS", "1000")

    candidates = [
        {"chunk_id": "big", "content": "激光焊接" * 40, "rrf_score": 0.9},
        {"chunk_id": "small", "content": "正常块", "rrf_score": 0.8},
    ]

    reranked = asyncio.run(reranker_mod.rerank_async("q", candidates, top_k=2, api_key="sf_key"))

    assert _NeverCalledAsyncClient.calls == 0
    assert [item.get("warning") for item in reranked] == ["oversize_skipped", "oversize_skipped"]
    assert logged[0]["short_circuit"] == "oversize_skipped"
    assert logged[0]["extra"]["event"] == "oversize_skipped"


def test_rerank_async_applies_provider_rate_limit_before_http(monkeypatch):
    import reranker_client as reranker_mod

    captured: list[dict[str, object]] = []

    async def _fake_wait(base_url: str | None, *, kind: str, token_count: int) -> float:
        captured.append({"base_url": base_url, "kind": kind, "token_count": token_count})
        return 0.0

    monkeypatch.setattr(reranker_mod.provider_rate_limit, "maybe_wait_for_rate_limit_async", _fake_wait)
    monkeypatch.setattr(reranker_mod.httpx, "AsyncClient", _StubAsyncClient)
    monkeypatch.delenv("SILICONFLOW_RERANK_BASE_URL", raising=False)
    monkeypatch.delenv("SILICONFLOW_RERANK_MODEL", raising=False)

    candidates = [
        {"chunk_id": "c1", "content": "doc A", "rrf_score": 0.8},
        {"chunk_id": "c2", "content": "doc B", "rrf_score": 0.7},
        {"chunk_id": "c3", "content": "doc C", "rrf_score": 0.6},
    ]

    reranked = asyncio.run(reranker_mod.rerank_async("laser query", candidates, api_key="sf_key"))

    assert [item["chunk_id"] for item in reranked] == ["c2", "c1", "c3"]
    assert len(captured) == 1
    assert captured[0]["base_url"] == "https://api.siliconflow.cn/v1/rerank"
    assert captured[0]["kind"] == "rerank"
    assert isinstance(captured[0]["token_count"], int)
    assert captured[0]["token_count"] > 0

