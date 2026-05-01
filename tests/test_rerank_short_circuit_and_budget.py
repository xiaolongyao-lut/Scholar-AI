"""Tests for rerank short-circuit + daily-budget guard + telemetry.

These tests verify rerank_async never reaches HTTP when:
* candidates already fit in top_k
* incoming similarity scores show a confident gap
* the daily budget is exhausted
* no API key is configured

They also verify telemetry lines are emitted to ``output/rerank_cost.jsonl``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


@pytest.fixture
def isolated_telemetry(monkeypatch, tmp_path):
    """Redirect rerank_budget output files into tmp_path and reset env."""
    import rerank_budget as rb
    import reranker_client as rc

    out_dir = tmp_path / "output"
    out_dir.mkdir()
    monkeypatch.setattr(rb, "_OUTPUT_DIR", out_dir, raising=True)
    monkeypatch.setattr(rb, "_BUDGET_FILE", out_dir / "rerank_budget_state.json", raising=True)
    monkeypatch.setattr(rb, "_TELEMETRY_FILE", out_dir / "rerank_cost.jsonl", raising=True)
    monkeypatch.setattr(rc, "RERANK_BUDGET_STATE_PATH", out_dir / "rerank_budget_state.json", raising=False)
    monkeypatch.setattr(rc, "RERANK_COST_LOG_PATH", out_dir / "rerank_cost.jsonl", raising=False)
    monkeypatch.setattr(rc, "_GLOBAL_RERANK_BUDGET_GUARD", None, raising=False)
    # Defaults: telemetry on, budget disabled, gap threshold 0.30.
    monkeypatch.setenv("RUNTIME_ENV_DISABLE_DOTENV", "1")
    monkeypatch.setenv("RERANK_TELEMETRY", "1")
    for key_name in (
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_RERANK_API_KEY",
        "SILICONFLOW_API_KEY",
        "SILICONFLOW_RERANK_API_KEY",
        "RERANK_API_KEY",
        "API_KEY",
    ):
        monkeypatch.delenv(key_name, raising=False)
    monkeypatch.delenv("RERANK_DAILY_BUDGET_CALLS", raising=False)
    monkeypatch.delenv("RERANK_DAILY_CALL_CAP", raising=False)
    monkeypatch.delenv("RERANK_DAILY_TOKEN_CAP", raising=False)
    monkeypatch.delenv("RERANK_DAILY_BUDGET_USD", raising=False)
    monkeypatch.delenv("RERANK_SHORT_CIRCUIT_GAP", raising=False)
    monkeypatch.delenv("RERANK_CACHE_ENABLED", raising=False)
    return out_dir


def _read_telemetry(out_dir: Path) -> list[dict]:
    fp = out_dir / "rerank_cost.jsonl"
    if not fp.exists():
        return []
    return [json.loads(line) for line in fp.read_text(encoding="utf-8").splitlines() if line.strip()]


def _no_http(monkeypatch):
    """Replace httpx.AsyncClient with a sentinel that fails the test if used."""
    import httpx

    def _boom(*_a, **_kw):
        raise AssertionError("HTTP call must not be made when short-circuited")

    monkeypatch.setattr(httpx, "AsyncClient", _boom)


def test_short_circuit_on_score_gap(isolated_telemetry, monkeypatch):
    import reranker_client as rc

    _no_http(monkeypatch)
    monkeypatch.setenv("RERANK_SHORT_CIRCUIT_GAP", "0.20")
    monkeypatch.setenv("RERANK_CACHE_ENABLED", "0")
    candidates = [
        {"id": "a", "content": "doc a", "dense_score": 0.95},
        {"id": "b", "content": "doc b", "dense_score": 0.40},
        {"id": "c", "content": "doc c", "dense_score": 0.35},
        {"id": "d", "content": "doc d", "dense_score": 0.30},
    ]
    out = asyncio.run(rc.rerank_async("q", candidates, top_k=2, api_key="sk-test"))
    assert len(out) == 2
    assert out[0]["id"] == "a"
    records = _read_telemetry(isolated_telemetry)
    assert any(r.get("short_circuit") == "score_gap" for r in records)


def test_no_short_circuit_when_gap_below_threshold(isolated_telemetry, monkeypatch):
    """When scores are close, short-circuit must NOT fire on the gap rule.

    We disable cache and provide no API key, which forces the no_api_key
    fallback path. The important check is the absence of short_circuit
    == "score_gap" in telemetry.
    """
    import reranker_client as rc

    _no_http(monkeypatch)
    monkeypatch.setenv("RERANK_SHORT_CIRCUIT_GAP", "0.50")
    monkeypatch.setenv("RERANK_CACHE_ENABLED", "0")
    candidates = [
        {"id": "a", "content": "doc a", "score": 0.50},
        {"id": "b", "content": "doc b", "score": 0.49},
        {"id": "c", "content": "doc c", "score": 0.48},
        {"id": "d", "content": "doc d", "score": 0.47},
    ]
    out = asyncio.run(rc.rerank_async("q", candidates, top_k=2, api_key=""))
    assert len(out) == 2
    assert all(item.get("rerank_fallback") is True for item in out)
    assert all(item.get("warning") == "no_api_key" for item in out)
    records = _read_telemetry(isolated_telemetry)
    assert all(r.get("short_circuit") != "score_gap" for r in records)
    assert any(r.get("short_circuit") == "no_api_key" for r in records)


def test_budget_blocks_when_exhausted(isolated_telemetry, monkeypatch):
    import reranker_client as rc

    _no_http(monkeypatch)
    monkeypatch.setenv("RERANK_DAILY_CALL_CAP", "1")
    monkeypatch.setenv("RERANK_DAILY_BUDGET_USD", "5")
    monkeypatch.setenv("RERANK_CACHE_ENABLED", "0")
    monkeypatch.setenv("RERANK_SHORT_CIRCUIT_GAP", "0")  # disable gap

    guard_cls = getattr(rc, "RerankBudgetGuard", None)
    if guard_cls is None:
        pytest.fail("RerankBudgetGuard is missing")
    guard = guard_cls(
        state_path=isolated_telemetry / "rerank_budget_state.json",
        telemetry_path=isolated_telemetry / "rerank_cost.jsonl",
    )
    first = guard.try_acquire("q", ["doc one"], model="qwen3-rerank")
    assert first["allowed"] is True
    monkeypatch.setattr(rc, "_GLOBAL_RERANK_BUDGET_GUARD", guard, raising=False)

    candidates = [
        {"id": str(i), "content": f"d{i}", "score": 0.5 - i * 0.01} for i in range(5)
    ]
    out = asyncio.run(rc.rerank_async("q", candidates, top_k=3, api_key="sk-test"))
    assert len(out) == 3
    assert all(item.get("warning") == "budget_capped" for item in out)
    records = _read_telemetry(isolated_telemetry)
    assert any(r.get("event") == "budget_capped" for r in records)


def test_budget_disabled_by_default(isolated_telemetry):
    import rerank_budget as rb

    assert rb.try_charge() is True
    assert rb.try_charge() is True
    assert rb.remaining() == 4998


def test_budget_resets_on_new_date(isolated_telemetry, monkeypatch):
    import rerank_budget as rb

    monkeypatch.setenv("RERANK_DAILY_CALL_CAP", "2")
    assert rb.try_charge() is True
    assert rb.try_charge() is True
    assert rb.try_charge() is False  # exhausted
    # Force a different date
    state_file = isolated_telemetry / "rerank_budget_state.json"
    state_file.write_text(
        json.dumps({"date": "1999-01-01", "call_count": 99, "token_count": 0, "cost_usd": 0.0}),
        encoding="utf-8",
    )
    assert rb.try_charge() is True
    assert rb.remaining() == 1


def test_budget_guard_persists_calls_tokens_and_cost(isolated_telemetry, monkeypatch):
    import reranker_client as rc

    monkeypatch.setenv("RERANK_DAILY_CALL_CAP", "10")
    monkeypatch.setenv("RERANK_DAILY_BUDGET_USD", "5")

    guard_cls = getattr(rc, "RerankBudgetGuard", None)
    if guard_cls is None:
        pytest.fail("RerankBudgetGuard is missing")

    state_path = isolated_telemetry / "rerank_budget_state.json"
    guard = guard_cls(state_path=state_path, telemetry_path=isolated_telemetry / "rerank_cost.jsonl")
    decision = guard.try_acquire("laser query", ["doc a", "doc b"], model="qwen3-rerank")

    assert decision["allowed"] is True
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["call_count"] == 1
    assert state["token_count"] > 0
    assert state["cost_usd"] > 0


def test_budget_guard_soft_warns_on_daily_usd_cap(isolated_telemetry, monkeypatch):
    import reranker_client as rc

    monkeypatch.setenv("RERANK_DAILY_CALL_CAP", "5000")
    monkeypatch.setenv("RERANK_DAILY_TOKEN_CAP", "5000")
    monkeypatch.setenv("RERANK_DAILY_BUDGET_USD", "0.001")
    monkeypatch.setattr(rc, "count_tokens", lambda _text: 1000)

    guard_cls = getattr(rc, "RerankBudgetGuard", None)
    if guard_cls is None:
        pytest.fail("RerankBudgetGuard is missing")

    guard = guard_cls(
        state_path=isolated_telemetry / "rerank_budget_state.json",
        telemetry_path=isolated_telemetry / "rerank_cost.jsonl",
    )
    decision = guard.try_acquire("q", ["doc one"], model="qwen3-rerank")

    assert decision["allowed"] is True
    assert decision["event"] == "budget_soft_warn"
    assert decision["reason"] == "daily_budget_usd"
    assert decision["cap_dim"] == "usd"


def test_rerank_budget_helper_uses_aligned_state_and_token_cap(isolated_telemetry, monkeypatch):
    import rerank_budget as rb
    import reranker_client as rc

    monkeypatch.setenv("RERANK_DAILY_CALL_CAP", "5")
    monkeypatch.setenv("RERANK_DAILY_TOKEN_CAP", "5")
    monkeypatch.setenv("RERANK_DAILY_BUDGET_USD", "5")
    monkeypatch.setattr(rc, "count_tokens", lambda _text: 2)

    assert rb.try_charge(query="q", documents=["doc"], model="qwen3-rerank") is True

    state = json.loads((isolated_telemetry / "rerank_budget_state.json").read_text(encoding="utf-8"))
    assert state["call_count"] == 1
    assert state["token_count"] == 4
    assert state["cost_usd"] > 0
    assert rb.remaining() == 4
    assert rb.try_charge(query="q", documents=["doc"], model="qwen3-rerank") is False


def test_successful_rerank_logs_budget_soft_warn_event(isolated_telemetry, monkeypatch):
    import reranker_client as rc

    class _Response:
        status_code = 200
        headers = {}
        text = ""

        def json(self):
            return {
                "results": [
                    {"index": 1, "relevance_score": 0.95},
                    {"index": 0, "relevance_score": 0.10},
                ]
            }

    class _AsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return _Response()

    import httpx

    monkeypatch.setenv("RERANK_CACHE_ENABLED", "0")
    monkeypatch.setenv("RERANK_SHORT_CIRCUIT_GAP", "0")
    monkeypatch.setenv("RERANK_DAILY_CALL_CAP", "5000")
    monkeypatch.setenv("RERANK_DAILY_TOKEN_CAP", "10000")
    monkeypatch.setenv("RERANK_DAILY_BUDGET_USD", "0.001")
    monkeypatch.setattr(rc, "count_tokens", lambda _text: 1_000)
    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    candidates = [
        {"id": "a", "content": "doc a", "score": 0.5},
        {"id": "b", "content": "doc b", "score": 0.4},
    ]
    out = asyncio.run(rc.rerank_async("q", candidates, top_k=2, api_key="sk-test"))

    assert [item["id"] for item in out] == ["b", "a"]
    assert all(item.get("warning") != "budget_capped" for item in out)
    records = _read_telemetry(isolated_telemetry)
    assert any(
        record.get("event") == "budget_soft_warn"
        and record.get("cap_dim") == "usd"
        and record.get("reason") == "daily_budget_usd"
        for record in records
    )

def test_empty_candidates_returns_empty_without_calling_provider(isolated_telemetry, monkeypatch):
    """Empty candidate lists are a pure local no-op."""
    import reranker_client as rc

    _no_http(monkeypatch)

    out = asyncio.run(rc.rerank_async("q", [], top_k=5, api_key="sk-test"))

    assert out == []


def test_single_candidate_short_circuits(isolated_telemetry, monkeypatch):
    """One candidate cannot be reordered, so provider IO is unnecessary.

    A11.R4.1 closed 2026-04-25: reranker_client.rerank_async now returns
    candidates[:top_k] without making any HTTP call when len(candidates) == 1.
    """
    import reranker_client as rc

    _no_http(monkeypatch)
    candidate = {"id": "only", "content": "single doc", "score": 0.5}

    out = asyncio.run(rc.rerank_async("q", [candidate], top_k=5, api_key="sk-test"))

    assert len(out) == 1
    assert out[0]["id"] == "only"


def test_top_n_larger_than_candidates(isolated_telemetry, monkeypatch):
    """Fallback paths must not pad beyond available candidates."""
    import reranker_client as rc

    _no_http(monkeypatch)
    monkeypatch.setenv("RERANK_CACHE_ENABLED", "0")
    monkeypatch.setenv("RERANK_SHORT_CIRCUIT_GAP", "0")
    candidates = [
        {"id": str(index), "content": f"doc {index}", "score": 1.0 - index * 0.01}
        for index in range(5)
    ]

    out = asyncio.run(rc.rerank_async("q", candidates, top_k=20, api_key=""))

    assert len(out) == 5
    assert [item["id"] for item in out] == ["0", "1", "2", "3", "4"]


def test_negative_or_zero_top_n_raises(isolated_telemetry, monkeypatch):
    """Non-positive top_k must raise ValueError (A11.R4.2 closed 2026-04-25)."""
    import reranker_client as rc

    _no_http(monkeypatch)
    candidates = [{"id": "a", "content": "doc a", "score": 1.0}]

    for top_k in (0, -1):
        with pytest.raises(ValueError, match="top_k"):
            asyncio.run(rc.rerank_async("q", candidates, top_k=top_k, api_key="sk-test"))
