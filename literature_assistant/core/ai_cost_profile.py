from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar


_REQUEST_COST_PROFILE: ContextVar[str | None] = ContextVar("request_cost_profile", default=None)


def normalize_cost_profile(value: str | None) -> str:
    raw = str(value or "balanced").strip().lower()
    if raw in {"save", "aggressive", "cost-save", "cost_save"}:
        return "aggressive"
    if raw in {"quality", "high-quality", "high_quality"}:
        return "quality"
    return "balanced"


def get_cost_profile() -> str:
    """Global cost profile for literature-assistant AI calls.

    Supported values:
    - balanced (default)
    - save / aggressive
    - quality
    """
    override = _REQUEST_COST_PROFILE.get()
    if override is not None:
        return normalize_cost_profile(override)
    return normalize_cost_profile(os.getenv("LITERATURE_AI_COST_PROFILE", "balanced"))


@contextmanager
def use_cost_profile(profile: str | None):
    token = _REQUEST_COST_PROFILE.set(normalize_cost_profile(profile))
    try:
        yield
    finally:
        _REQUEST_COST_PROFILE.reset(token)


def is_aggressive_cost_save() -> bool:
    return get_cost_profile() == "aggressive"


def rerank_cache_enabled() -> bool:
    raw = str(os.getenv("RERANK_CACHE_ENABLED", "1")).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def rerank_short_circuit_score_gap() -> float:
    """If the top-2 score gap among incoming candidates exceeds this value,
    skip rerank entirely (the ordering is already confident enough).

    0 disables the gap-based short-circuit. Default 0.30.
    """
    try:
        return float(os.getenv("RERANK_SHORT_CIRCUIT_GAP", "0.30"))
    except (TypeError, ValueError):
        return 0.30


def rerank_daily_budget_calls() -> int:
    """Maximum number of *non-cached* rerank API calls per UTC day.

    0 disables the budget guard (default — opt-in safety only).
    """
    try:
        return max(0, int(os.getenv("RERANK_DAILY_BUDGET_CALLS", "0")))
    except (TypeError, ValueError):
        return 0


def rerank_telemetry_enabled() -> bool:
    raw = str(os.getenv("RERANK_TELEMETRY", "1")).strip().lower()
    return raw not in {"0", "false", "no", "off"}
