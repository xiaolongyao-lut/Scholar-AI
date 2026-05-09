"""Smooth, per-(provider, kind) request pacing.

Replaces the previous RPM/TPM sliding-window limiter. Rationale: the upstream
provider (SiliconFlow / DashScope / OpenAI / ...) already enforces its own rate
limits, so we do not try to mirror their per-model RPM/TPM tables.

Instead we apply a small minimum-interval pacer between successive HTTP
requests of the same `(provider, kind)`, so that bursts (e.g. cache-hit hot
loops) do not accidentally hammer the provider. For typical embedding / rerank
calls (~150-800ms server-side) the pacer is a no-op; it only kicks in when
client-side calls would otherwise fire faster than the configured interval.

Public API is intentionally unchanged from the old limiter so existing call
sites in `chunk_vector_store.py` and `reranker_client.py` keep working:

    maybe_wait_for_rate_limit_sync(base_url, *, kind, token_count) -> float
    maybe_wait_for_rate_limit_async(base_url, *, kind, token_count) -> float

`token_count` is accepted but ignored (RPM/TPM enforcement removed).
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from dataclasses import dataclass
from typing import Literal

ProviderRateKind = Literal["embedding", "rerank"]

# Conservative defaults. Picked to stay well under known provider ceilings
# while being a no-op for normal request latencies (>=150ms typical).
#   30ms => <= ~33 req/s/kind  (SiliconFlow ceiling: 2000 RPM ~= 33 req/s)
#   20ms => <= ~50 req/s/kind  (DashScope qwen3-rerank: 5400 RPM ~= 90 req/s)
_DEFAULT_MIN_INTERVAL_MS: dict[tuple[str, str], int] = {
    ("siliconflow", "embedding"): 30,
    ("siliconflow", "rerank"): 30,
    ("dashscope", "embedding"): 20,
    ("dashscope", "rerank"): 20,
}

_PACERS: dict[tuple[str, str, int], "MinIntervalPacer"] = {}
_PACERS_LOCK = threading.Lock()


@dataclass(frozen=True)
class PacingConfig:
    provider: str
    kind: ProviderRateKind
    min_interval_ms: int


class MinIntervalPacer:
    """Ensures consecutive `acquire` calls are spaced by >= min_interval."""

    def __init__(self, *, min_interval_ms: int) -> None:
        self.min_interval_ms = max(0, int(min_interval_ms))
        self._min_interval = self.min_interval_ms / 1000.0
        self._lock = threading.Lock()
        self._next_allowed: float = 0.0  # monotonic timestamp

    def _reserve_or_wait(self, now: float) -> float:
        if self._min_interval <= 0.0:
            return 0.0
        if now >= self._next_allowed:
            self._next_allowed = now + self._min_interval
            return 0.0
        wait = self._next_allowed - now
        # Reserve our slot now so concurrent callers serialize even while sleeping.
        self._next_allowed += self._min_interval
        return wait

    def acquire_sync(self) -> float:
        with self._lock:
            wait = self._reserve_or_wait(time.monotonic())
        if wait > 0.0:
            time.sleep(wait)
        return wait

    async def acquire_async(self) -> float:
        with self._lock:
            wait = self._reserve_or_wait(time.monotonic())
        if wait > 0.0:
            await asyncio.sleep(wait)
        return wait


def _provider_from_base_url(base_url: str | None) -> str:
    lowered = str(base_url or "").strip().lower()
    if "siliconflow.cn" in lowered:
        return "siliconflow"
    if "dashscope.aliyuncs.com" in lowered:
        return "dashscope"
    return "generic"


def _read_env_int(*names: str) -> int | None:
    for name in names:
        raw = os.getenv(name)
        if raw is None or not str(raw).strip():
            continue
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            continue
    return None


def resolve_pacing_config(base_url: str | None, *, kind: ProviderRateKind) -> PacingConfig | None:
    """Return the active pacing config for `(provider, kind)`, or None to skip."""
    provider = _provider_from_base_url(base_url)
    prefix = kind.upper()
    provider_prefix = provider.upper()

    override = _read_env_int(
        f"{provider_prefix}_{prefix}_MIN_INTERVAL_MS",
        f"{prefix}_MIN_INTERVAL_MS",
    )
    if override is not None:
        if override <= 0:
            return None
        return PacingConfig(provider=provider, kind=kind, min_interval_ms=override)

    default = _DEFAULT_MIN_INTERVAL_MS.get((provider, kind), 0)
    if default <= 0:
        return None
    return PacingConfig(provider=provider, kind=kind, min_interval_ms=default)


def _pacer_for(config: PacingConfig) -> MinIntervalPacer:
    key = (config.provider, config.kind, config.min_interval_ms)
    with _PACERS_LOCK:
        pacer = _PACERS.get(key)
        if pacer is None:
            pacer = MinIntervalPacer(min_interval_ms=config.min_interval_ms)
            _PACERS[key] = pacer
        return pacer


def _reset_cache_for_tests() -> None:
    with _PACERS_LOCK:
        _PACERS.clear()


def maybe_wait_for_rate_limit_sync(
    base_url: str | None,
    *,
    kind: ProviderRateKind,
    token_count: int = 0,  # accepted for backward compat; ignored.
) -> float:
    del token_count
    config = resolve_pacing_config(base_url, kind=kind)
    if config is None:
        return 0.0
    return _pacer_for(config).acquire_sync()


async def maybe_wait_for_rate_limit_async(
    base_url: str | None,
    *,
    kind: ProviderRateKind,
    token_count: int = 0,  # accepted for backward compat; ignored.
) -> float:
    del token_count
    config = resolve_pacing_config(base_url, kind=kind)
    if config is None:
        return 0.0
    return await _pacer_for(config).acquire_async()
