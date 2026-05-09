from __future__ import annotations

import asyncio
import json

import pytest


@pytest.fixture
def isolated_budget_env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    import reranker_client as rc

    out_dir = tmp_path / "output"
    out_dir.mkdir()
    monkeypatch.setattr(rc, "RERANK_BUDGET_STATE_PATH", out_dir / "rerank_budget_state.json", raising=False)
    monkeypatch.setattr(rc, "RERANK_COST_LOG_PATH", out_dir / "rerank_cost.jsonl", raising=False)
    monkeypatch.setattr(rc, "_GLOBAL_RERANK_BUDGET_GUARD", None, raising=False)
    monkeypatch.setenv("RERANK_CACHE_ENABLED", "0")
    monkeypatch.setenv("RERANK_SHORT_CIRCUIT_GAP", "0")
    return out_dir


def test_rerank_budget_falls_back_after_daily_threshold(
    isolated_budget_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    import reranker_client as rc

    monkeypatch.setenv("RERANK_DAILY_CALL_CAP", "1")
    monkeypatch.setenv("RERANK_DAILY_BUDGET_USD", "5")

    def _boom(*_args, **_kwargs):
        raise AssertionError("HTTP should not be called when budget is capped")

    monkeypatch.setattr(httpx, "AsyncClient", _boom)

    guard = rc.RerankBudgetGuard(
        state_path=isolated_budget_env / "rerank_budget_state.json",
        telemetry_path=isolated_budget_env / "rerank_cost.jsonl",
    )
    first = guard.try_acquire("q", ["doc one"], model="qwen3-rerank")
    assert first["allowed"] is True
    monkeypatch.setattr(rc, "_GLOBAL_RERANK_BUDGET_GUARD", guard, raising=False)

    candidates = [{"id": str(i), "content": f"doc-{i}", "score": 0.9 - i * 0.05} for i in range(4)]
    ranked = asyncio.run(rc.rerank_async("query", candidates, top_k=2, api_key="sk-test"))

    assert len(ranked) == 2
    assert all(item.get("warning") == "budget_capped" for item in ranked)


def test_rerank_budget_guard_resets_across_day_boundary(
    isolated_budget_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import reranker_client as rc

    monkeypatch.setenv("RERANK_DAILY_CALL_CAP", "1")
    monkeypatch.setenv("RERANK_DAILY_BUDGET_USD", "5")

    state_path = isolated_budget_env / "rerank_budget_state.json"
    state_path.write_text(
        json.dumps({"date": "1999-01-01", "call_count": 99, "token_count": 999, "cost_usd": 9.99}),
        encoding="utf-8",
    )

    guard = rc.RerankBudgetGuard(state_path=state_path, telemetry_path=isolated_budget_env / "rerank_cost.jsonl")
    decision = guard.try_acquire("query", ["doc"], model="qwen3-rerank")

    assert decision["allowed"] is True
    assert decision["state"]["date"] != "1999-01-01"
    assert decision["state"]["call_count"] == 1


def test_rerank_budget_guard_recovers_from_corrupted_state_file(
    isolated_budget_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import reranker_client as rc

    monkeypatch.setenv("RERANK_DAILY_CALL_CAP", "5")
    monkeypatch.setenv("RERANK_DAILY_BUDGET_USD", "5")

    state_path = isolated_budget_env / "rerank_budget_state.json"
    state_path.write_text("{bad json", encoding="utf-8")

    guard = rc.RerankBudgetGuard(state_path=state_path, telemetry_path=isolated_budget_env / "rerank_cost.jsonl")
    decision = guard.try_acquire("query", ["doc"], model="qwen3-rerank")

    assert decision["allowed"] is True
    recovered_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert recovered_state["call_count"] == 1
    assert recovered_state["token_count"] > 0
    assert recovered_state["cost_usd"] > 0


def test_rerank_budget_guard_blocks_on_daily_token_cap(
    isolated_budget_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import reranker_client as rc

    monkeypatch.setenv("RERANK_DAILY_CALL_CAP", "5")
    monkeypatch.setenv("RERANK_DAILY_TOKEN_CAP", "3")
    monkeypatch.setenv("RERANK_DAILY_BUDGET_USD", "5")
    monkeypatch.setattr(rc, "count_tokens", lambda _text: 2)

    guard = rc.RerankBudgetGuard(
        state_path=isolated_budget_env / "rerank_budget_state.json",
        telemetry_path=isolated_budget_env / "rerank_cost.jsonl",
    )
    decision = guard.try_acquire("query", ["doc"], model="qwen3-rerank")

    assert decision["allowed"] is False
    assert decision["event"] == "budget_capped"
    assert decision["reason"] == "daily_token_cap"
    assert decision["cap_dim"] == "token"
