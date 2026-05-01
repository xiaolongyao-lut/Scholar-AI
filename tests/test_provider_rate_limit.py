"""Tests for the min-interval pacer in `provider_rate_limit`.

We do NOT test RPM/TPM windows anymore -- provider enforces those server-side.
We DO test that bursts within `min_interval_ms` are smoothed out.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_pacer_cache():
    import provider_rate_limit as prl

    prl._reset_cache_for_tests()
    yield
    prl._reset_cache_for_tests()


def test_first_call_does_not_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    import provider_rate_limit as prl

    fake_now = {"value": 100.0}
    sleeps: list[float] = []

    monkeypatch.setattr(prl.time, "monotonic", lambda: fake_now["value"])
    monkeypatch.setattr(prl.time, "sleep", lambda s: sleeps.append(s))

    waited = prl.maybe_wait_for_rate_limit_sync(
        "https://api.siliconflow.cn/v1/embeddings", kind="embedding", token_count=10
    )

    assert waited == 0.0
    assert sleeps == []


def test_second_call_within_interval_waits_remaining_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    import provider_rate_limit as prl

    # Default for siliconflow embedding = 30ms.
    fake_now = {"value": 0.0}
    sleeps: list[float] = []

    monkeypatch.setattr(prl.time, "monotonic", lambda: fake_now["value"])

    def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        fake_now["value"] += seconds

    monkeypatch.setattr(prl.time, "sleep", _fake_sleep)

    base_url = "https://api.siliconflow.cn/v1/embeddings"

    first = prl.maybe_wait_for_rate_limit_sync(base_url, kind="embedding", token_count=1)
    # Advance clock by 10ms (less than the 30ms interval).
    fake_now["value"] += 0.010
    second = prl.maybe_wait_for_rate_limit_sync(base_url, kind="embedding", token_count=1)

    assert first == 0.0
    # First call reserved up to t=0.030; second arrives at t=0.010 -> wait 0.020s.
    assert second == pytest.approx(0.020, abs=1e-6)
    assert sleeps == [pytest.approx(0.020, abs=1e-6)]


def test_call_after_interval_does_not_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    import provider_rate_limit as prl

    fake_now = {"value": 0.0}
    sleeps: list[float] = []

    monkeypatch.setattr(prl.time, "monotonic", lambda: fake_now["value"])
    monkeypatch.setattr(prl.time, "sleep", lambda s: sleeps.append(s))

    base_url = "https://api.siliconflow.cn/v1/rerank"

    prl.maybe_wait_for_rate_limit_sync(base_url, kind="rerank", token_count=1)
    fake_now["value"] += 0.100  # well past the 30ms interval
    second = prl.maybe_wait_for_rate_limit_sync(base_url, kind="rerank", token_count=1)

    assert second == 0.0
    assert sleeps == []


@pytest.mark.asyncio
async def test_async_pacing_uses_asyncio_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    import provider_rate_limit as prl

    fake_now = {"value": 0.0}
    sleeps: list[float] = []

    monkeypatch.setattr(prl.time, "monotonic", lambda: fake_now["value"])

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        fake_now["value"] += seconds

    monkeypatch.setattr(prl.asyncio, "sleep", _fake_sleep)

    base_url = "https://api.siliconflow.cn/v1/embeddings"

    first = await prl.maybe_wait_for_rate_limit_async(base_url, kind="embedding", token_count=5)
    second = await prl.maybe_wait_for_rate_limit_async(base_url, kind="embedding", token_count=5)

    assert first == 0.0
    # Two back-to-back calls at t=0 -> second waits the full 30ms gap.
    assert second == pytest.approx(0.030, abs=1e-6)
    assert sleeps == [pytest.approx(0.030, abs=1e-6)]


def test_dashscope_default_is_20ms(monkeypatch: pytest.MonkeyPatch) -> None:
    import provider_rate_limit as prl

    monkeypatch.delenv("DASHSCOPE_EMBEDDING_MIN_INTERVAL_MS", raising=False)
    monkeypatch.delenv("EMBEDDING_MIN_INTERVAL_MS", raising=False)

    config = prl.resolve_pacing_config(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
        kind="embedding",
    )

    assert config is not None
    assert config.provider == "dashscope"
    assert config.min_interval_ms == 20


def test_generic_provider_has_no_default_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    import provider_rate_limit as prl

    monkeypatch.delenv("GENERIC_EMBEDDING_MIN_INTERVAL_MS", raising=False)
    monkeypatch.delenv("EMBEDDING_MIN_INTERVAL_MS", raising=False)

    config = prl.resolve_pacing_config(
        "https://api.openai.com/v1/embeddings",
        kind="embedding",
    )

    assert config is None


def test_env_override_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    import provider_rate_limit as prl

    monkeypatch.setenv("SILICONFLOW_EMBEDDING_MIN_INTERVAL_MS", "75")

    config = prl.resolve_pacing_config(
        "https://api.siliconflow.cn/v1/embeddings",
        kind="embedding",
    )

    assert config is not None
    assert config.min_interval_ms == 75


def test_env_override_zero_disables_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    import provider_rate_limit as prl

    monkeypatch.setenv("SILICONFLOW_RERANK_MIN_INTERVAL_MS", "0")

    config = prl.resolve_pacing_config(
        "https://api.siliconflow.cn/v1/rerank",
        kind="rerank",
    )

    assert config is None


def test_kind_level_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import provider_rate_limit as prl

    monkeypatch.delenv("SILICONFLOW_EMBEDDING_MIN_INTERVAL_MS", raising=False)
    monkeypatch.setenv("EMBEDDING_MIN_INTERVAL_MS", "42")

    config = prl.resolve_pacing_config(
        "https://api.siliconflow.cn/v1/embeddings",
        kind="embedding",
    )

    assert config is not None
    assert config.min_interval_ms == 42
