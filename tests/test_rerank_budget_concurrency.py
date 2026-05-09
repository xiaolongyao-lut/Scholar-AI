from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture()
def isolated_budget_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    import rerank_budget as rb

    out_dir = tmp_path / "out"
    monkeypatch.setattr(rb, "_OUTPUT_DIR", out_dir, raising=True)
    monkeypatch.setattr(rb, "_BUDGET_FILE", out_dir / "rerank_budget_state.json", raising=True)
    monkeypatch.setenv("RERANK_DAILY_CALL_CAP", "10")
    return out_dir


@pytest.mark.asyncio
async def test_concurrent_decrement_never_goes_negative(isolated_budget_files: Path) -> None:
    """Thread lock must cap concurrent reservations at the configured daily limit."""
    import rerank_budget as rb

    results = await asyncio.gather(*[asyncio.to_thread(rb.try_charge) for _ in range(100)])
    state = json.loads((isolated_budget_files / "rerank_budget_state.json").read_text(encoding="utf-8"))

    assert sum(1 for item in results if item is True) == 10
    assert sum(1 for item in results if item is False) == 90
    assert state["call_count"] == 10
    assert rb.remaining() == 0


@pytest.mark.asyncio
async def test_concurrent_reset_is_atomic(isolated_budget_files: Path) -> None:
    """Date-bound reset must never expose negative or malformed state."""
    import rerank_budget as rb

    budget_file = isolated_budget_files / "rerank_budget_state.json"
    budget_file.parent.mkdir(parents=True, exist_ok=True)
    budget_file.write_text(
        json.dumps({"date": "1999-01-01", "call_count": 99, "token_count": 0, "cost_usd": 0.0}),
        encoding="utf-8",
    )

    results = await asyncio.gather(*[asyncio.to_thread(rb.try_charge) for _ in range(25)])
    state: dict[str, Any] = json.loads(budget_file.read_text(encoding="utf-8"))

    assert isinstance(state.get("date"), str)
    assert 0 <= int(state["call_count"]) <= 10
    assert sum(1 for item in results if item is True) <= 10
    assert rb.remaining() is not None
    assert rb.remaining() >= 0
