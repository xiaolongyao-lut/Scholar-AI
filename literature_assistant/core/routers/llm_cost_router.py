from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from project_paths import output_path

_LOG_FILE = output_path("llm_cost.jsonl")
_MAX_LOG_BYTES = 256 * 1024 * 1024

router = APIRouter(prefix="/llm/cost", tags=["Statistics"])


def _empty_bucket() -> dict[str, int | float]:
    return {"calls": 0, "total_tokens": 0, "total_cost_usd": 0.0}


def _normalize_cost(value: float) -> float:
    return round(value, 10)


def _parse_row_date(row: dict[str, object]) -> date:
    raw_ts = str(row.get("ts") or "").strip()
    if not raw_ts:
        raise ValueError("missing ts")
    return datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).date()


def _read_cost_aggregate(start: date, end: date) -> dict[str, object]:
    if _LOG_FILE.exists() and _LOG_FILE.stat().st_size > _MAX_LOG_BYTES:
        raise HTTPException(
            status_code=503,
            detail="LLM cost log exceeds 256 MB; archive output/llm_cost.jsonl before querying again",
        )

    by_task: dict[str, dict[str, int | float]] = {}
    by_model: dict[str, dict[str, int | float]] = {}
    malformed_lines = 0
    total_calls = 0
    total_tokens = 0
    total_cost_usd = 0.0

    if not _LOG_FILE.exists():
        return {
            "total_calls": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "by_task": {},
            "by_model": {},
            "meta": {"malformed_lines": 0},
        }

    with _LOG_FILE.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                malformed_lines += 1
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("row must be an object")
                row_date = _parse_row_date(row)
                total_tokens_value = int(row.get("total_tokens") or 0)
                cost_value = float(row.get("cost_usd") or 0.0)
                task = str(row.get("task") or "")
                model = str(row.get("model") or "")
            except (ValueError, TypeError, json.JSONDecodeError):
                malformed_lines += 1
                continue

            if row_date < start or row_date > end:
                continue

            total_calls += 1
            total_tokens += total_tokens_value
            total_cost_usd += cost_value

            task_bucket = by_task.setdefault(task, _empty_bucket())
            task_bucket["calls"] += 1
            task_bucket["total_tokens"] += total_tokens_value
            task_bucket["total_cost_usd"] = _normalize_cost(task_bucket["total_cost_usd"] + cost_value)

            model_bucket = by_model.setdefault(model, _empty_bucket())
            model_bucket["calls"] += 1
            model_bucket["total_tokens"] += total_tokens_value
            model_bucket["total_cost_usd"] = _normalize_cost(model_bucket["total_cost_usd"] + cost_value)

    return {
        "total_calls": total_calls,
        "total_tokens": total_tokens,
        "total_cost_usd": _normalize_cost(total_cost_usd),
        "by_task": by_task,
        "by_model": by_model,
        "meta": {"malformed_lines": malformed_lines},
    }


@router.get("/today")
async def get_llm_cost_today() -> dict[str, object]:
    today = date.today()
    payload = _read_cost_aggregate(today, today)
    return {"date": today.isoformat(), **payload}


@router.get("/range")
async def get_llm_cost_range(
    start: date = Query(..., description="Inclusive start date in YYYY-MM-DD format"),
    end: date = Query(..., description="Inclusive end date in YYYY-MM-DD format"),
) -> dict[str, object]:
    if start > end:
        raise HTTPException(status_code=422, detail="start must be on or before end")
    payload = _read_cost_aggregate(start, end)
    return {"start": start.isoformat(), "end": end.isoformat(), **payload}
