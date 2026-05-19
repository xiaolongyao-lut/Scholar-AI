"""Compatibility helpers for the rerank budget contract.

This module now mirrors ``reranker_client.RerankBudgetGuard`` so older callers
do not drift onto a separate interpretation:

* hard caps: daily call count and daily token count
* USD budget: soft warning / telemetry only, never a hard fallback
* state file: ``output/rerank_budget_state.json`` with the same schema used by
  the live reranker path
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_cost_profile import rerank_telemetry_enabled
from project_paths import output_path

_BUDGET_LOCK = threading.Lock()
_TELEMETRY_LOCK = threading.Lock()

_OUTPUT_DIR = output_path()
_BUDGET_FILE = _OUTPUT_DIR / "rerank_budget_state.json"
_TELEMETRY_FILE = _OUTPUT_DIR / "rerank_cost.jsonl"


def _today_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _read_state() -> dict[str, Any]:
    if not _BUDGET_FILE.exists():
        return {"date": _today_utc(), "call_count": 0, "token_count": 0, "cost_usd": 0.0}
    try:
        data = json.loads(_BUDGET_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {"date": _today_utc(), "call_count": 0, "token_count": 0, "cost_usd": 0.0}
    if not isinstance(data, dict):
        return {"date": _today_utc(), "call_count": 0, "token_count": 0, "cost_usd": 0.0}
    legacy_count = data.get("count")
    return {
        "date": str(data.get("date") or _today_utc()),
        "call_count": max(0, int(data.get("call_count", legacy_count) or 0)),
        "token_count": max(0, int(data.get("token_count") or 0)),
        "cost_usd": max(0.0, float(data.get("cost_usd") or 0.0)),
    }


def _make_guard():
    from reranker_client import RerankBudgetGuard

    return RerankBudgetGuard(state_path=_BUDGET_FILE, telemetry_path=_TELEMETRY_FILE)


def _daily_call_cap() -> int:
    from reranker_client import _daily_call_cap as _client_daily_call_cap

    return _client_daily_call_cap()


def try_charge(
    query: str = "",
    documents: list[str] | None = None,
    *,
    model: str = "",
) -> bool:
    """Reserve one rerank attempt under the live budget contract."""
    with _BUDGET_LOCK:
        decision = _make_guard().try_acquire(query, list(documents or []), model=model)
    return bool(decision.get("allowed"))


def remaining() -> int | None:
    """Remaining call slots today, or ``None`` if the hard cap is disabled."""
    cap = _daily_call_cap()
    if cap <= 0:
        return None
    with _BUDGET_LOCK:
        state = _read_state()
    if state["date"] != _today_utc():
        return cap
    return max(0, cap - state["call_count"])


def log_call(
    *,
    model: str,
    n_docs: int,
    latency_ms: float,
    cached: bool = False,
    short_circuit: str | None = None,
    budget_blocked: bool = False,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one JSON line summarising a rerank attempt."""
    if not rerank_telemetry_enabled():
        return
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": str(model or ""),
        "n_docs": int(n_docs),
        "latency_ms": round(float(latency_ms), 2),
        "cached": bool(cached),
        "short_circuit": short_circuit,
        "budget_blocked": bool(budget_blocked),
    }
    if budget_blocked:
        record["event"] = "budget_capped"
    if extra:
        record.update({str(k): v for k, v in extra.items()})
    line = json.dumps(record, ensure_ascii=False) + "\n"
    try:
        with _TELEMETRY_LOCK:
            _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            with _TELEMETRY_FILE.open("a", encoding="utf-8") as fh:
                fh.write(line)
    except OSError:
        pass


__all__ = ["try_charge", "remaining", "log_call"]
