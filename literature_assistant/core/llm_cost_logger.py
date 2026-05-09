"""Append-only LLM cost / usage telemetry.

One JSON line per LLM call goes to ``output/llm_cost.jsonl``. The
record is intentionally minimal so it can be parsed with ``jq`` or
loaded into pandas for daily roll-ups; nothing here issues network
calls or affects the LLM response itself.

Telemetry is best-effort: any IO failure is swallowed silently to
keep production paths from breaking on disk-full or permission
issues.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_pricing import estimate_cost_usd, is_known_model
from project_paths import output_path

_LOCK = threading.Lock()
_OUTPUT_DIR = output_path()
_LOG_FILE = _OUTPUT_DIR / "llm_cost.jsonl"


def _enabled() -> bool:
    raw = str(os.getenv("LLM_COST_TELEMETRY", "1")).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def log_llm_call(
    *,
    model: str | None,
    task: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: float,
    status: str = "ok",
    cache_status: str = "miss",
    decision: str = "invoke",
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one usage / cost record. Never raises."""
    if not _enabled():
        return
    try:
        cost = estimate_cost_usd(
            model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        record = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "model": str(model or ""),
            "task": str(task or ""),
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "total_tokens": int(prompt_tokens or 0) + int(completion_tokens or 0),
            "cost_usd": cost,
            "latency_ms": round(float(latency_ms or 0.0), 2),
            "status": str(status or "ok"),
            "pricing_known": is_known_model(model),
            "cache_status": str(cache_status or "miss"),
            "decision": str(decision or "invoke"),
        }
        if extra:
            record.update({str(k): v for k, v in extra.items()})
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with _LOCK:
            _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            with _LOG_FILE.open("a", encoding="utf-8") as fh:
                fh.write(line)
    except (OSError, ValueError, TypeError):
        # Telemetry must never break the caller.
        return


__all__ = ["log_llm_call"]
