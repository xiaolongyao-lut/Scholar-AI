# -*- coding: utf-8 -*-
"""Chart agent observability — JSONL append for intent / spec events.

Why:
    P3.1c (per ``docs/plans/active/2026-05-09-rag-pro-borrow-features.md``)
    needs evidence about chart-intent precision and spec failure modes
    before defaulting ``LITERATURE_ENABLE_CHART_AGENT`` to on. JSONL is
    append-only, easy to grep and analyze, and survives without a DB.

Privacy:
    Raw queries can carry research direction or unpublished hypotheses.
    We persist only a 12-char SHA-256 prefix, query length, and event
    metadata — enough to dedup and group, not enough to reconstruct the
    text.

Failure isolation:
    Metrics must never break the chat handler. Every helper here wraps
    file I/O in try/except and logs at warning level on failure.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from project_paths import runtime_state_path


_logger = logging.getLogger("ChartMetrics")
_LOCK = threading.Lock()

ChartEventType = Literal[
    "intent_seed_match",
    "intent_llm_match",
    "intent_llm_no",
    "intent_llm_error",
    "spec_success",
    "spec_invalid_json",
    "spec_sanitizer_reject",
    "spec_llm_error",
]

_VALID_EVENTS: frozenset[str] = frozenset(
    {
        "intent_seed_match",
        "intent_llm_match",
        "intent_llm_no",
        "intent_llm_error",
        "spec_success",
        "spec_invalid_json",
        "spec_sanitizer_reject",
        "spec_llm_error",
    }
)


def _metrics_path() -> Path:
    """Return the JSONL file location, resolved each call so tests can
    monkeypatch ``runtime_state_path`` without re-importing this module."""
    return runtime_state_path("chart_intent_metrics.jsonl")


def _hash_query(query: str) -> str:
    """Stable 12-char SHA-256 prefix of the (lowercased) query."""
    digest = hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()
    return digest[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def record_event(
    event_type: ChartEventType,
    query: str,
    *,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one chart-agent event to the metrics JSONL.

    Silent on failure: any I/O error is logged once at warning level so the
    chat path never inherits a metrics fault.
    """
    if event_type not in _VALID_EVENTS:
        _logger.warning("chart_metrics: unknown event_type %r — skipping", event_type)
        return
    payload: dict[str, Any] = {
        "ts": _now_iso(),
        "event": event_type,
        "query_hash": _hash_query(query) if query else None,
        "query_len": len(query or ""),
    }
    if extra:
        for key, value in extra.items():
            if key in payload:
                continue
            payload[key] = value
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    try:
        path = _metrics_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass  # best-effort durability
    except Exception as exc:  # noqa: BLE001 — metrics must never break chat
        _logger.warning("chart_metrics: failed to write %s: %s", event_type, exc)


def read_events(limit: int | None = None) -> list[dict[str, Any]]:
    """Read recorded events for tests / quick inspection. Tail-first."""
    path = _metrics_path()
    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        _logger.warning("chart_metrics: failed to read events: %s", exc)
        return []
    parsed: list[dict[str, Any]] = []
    for raw in lines:
        text = raw.strip()
        if not text:
            continue
        try:
            parsed.append(json.loads(text))
        except json.JSONDecodeError:
            continue
    if limit is not None and limit >= 0:
        return parsed[-limit:]
    return parsed
