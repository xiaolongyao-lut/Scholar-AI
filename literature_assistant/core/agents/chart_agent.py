# -*- coding: utf-8 -*-
"""ChartAgent — produce a sanitized ECharts spec from context chunks.

Pattern adapted from RAG-Pro ``backend/app/agents/chart_agent.py``: extract
JSON from LLM output, then strictly allowlist option fields. Anything not
on the allowlist (functions, HTML strings, event handlers, raw JS) is
discarded so the frontend can safely pass the spec into ``ReactECharts``.

P3 spike status:
- LLM call deferred — this spike returns a deterministic placeholder spec
  built from chunk titles, so the wiring + sanitizer + fallback path can
  be tested without burning API budget.
- Production P3.1 will replace ``_build_placeholder_spec`` with a real
  ``model_call_gateway`` call + ``json.loads`` extraction + sanitizer.
"""

from __future__ import annotations

import json
from typing import Any, Mapping


_ALLOWED_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "title",
        "tooltip",
        "legend",
        "grid",
        "xAxis",
        "yAxis",
        "radar",
        "series",
        "dataset",
        "color",
        "backgroundColor",
        "animation",
    }
)
_ALLOWED_SERIES_TYPES: frozenset[str] = frozenset(
    {"line", "bar", "pie", "scatter", "radar", "candlestick"}
)
_FORBIDDEN_KEY_SUBSTRINGS: tuple[str, ...] = ("formatter", "renderer", "rich", "html")


def _scrub_value(value: Any) -> Any:
    """Strip dangerous primitives — functions, callables, raw HTML strings."""
    if callable(value):
        return None
    if isinstance(value, str):
        text = value.strip()
        if text.lower().startswith("function") or text.startswith("<"):
            return None
        return text
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        scrubbed = [_scrub_value(item) for item in value]
        return [item for item in scrubbed if item is not None]
    if isinstance(value, Mapping):
        return _scrub_mapping(value)
    return None


def _scrub_mapping(obj: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in obj.items():
        if not isinstance(key, str):
            continue
        if any(token in key.lower() for token in _FORBIDDEN_KEY_SUBSTRINGS):
            continue
        scrubbed = _scrub_value(val)
        if scrubbed is None:
            continue
        out[key] = scrubbed
    return out


def sanitize_echarts_option(option: Any) -> dict[str, Any] | None:
    """Return a safe ECharts option dict, or ``None`` if invalid.

    Validation rules:
        - Top-level must be a JSON object.
        - Only keys in ``_ALLOWED_TOP_LEVEL_KEYS`` are kept.
        - ``series`` must be a list, each item must have ``type`` in
          ``_ALLOWED_SERIES_TYPES`` and a ``data`` array.
        - Keys containing ``formatter``/``renderer``/``rich``/``html`` are
          dropped to block JS injection.
    """
    if not isinstance(option, Mapping):
        return None
    safe: dict[str, Any] = {}
    for key in _ALLOWED_TOP_LEVEL_KEYS:
        if key in option:
            safe[key] = _scrub_value(option[key])
    series = safe.get("series")
    if not isinstance(series, list) or not series:
        return None
    valid_series: list[dict[str, Any]] = []
    for item in series:
        if not isinstance(item, dict):
            continue
        series_type = item.get("type")
        if series_type not in _ALLOWED_SERIES_TYPES:
            continue
        if not isinstance(item.get("data"), list):
            continue
        valid_series.append(item)
    if not valid_series:
        return None
    safe["series"] = valid_series
    return safe


def _build_placeholder_spec(query: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Stub spec used until LLM generation is wired in P3.1."""
    sources = [str(chunk.get("source") or f"chunk-{i}")[:40] for i, chunk in enumerate(chunks[:8])]
    counts = [1] * len(sources) if sources else [1]
    if not sources:
        sources = ["(no context)"]
    return {
        "title": {"text": query[:60] or "Chart"},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": sources},
        "yAxis": {"type": "value"},
        "series": [
            {
                "type": "bar",
                "name": "context coverage",
                "data": counts,
            }
        ],
    }


def generate_chart_spec(
    query: str,
    chunks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """P3.0 spike: build a placeholder spec, sanitize, return safe option.

    Returns ``None`` if sanitization rejects the spec (caller falls back to
    plain text). Future P3.1 will swap the placeholder for a real LLM call.
    """
    candidate = _build_placeholder_spec(query, chunks)
    return sanitize_echarts_option(candidate)


def parse_llm_chart_json(text: str) -> dict[str, Any] | None:
    """Extract a JSON object from raw LLM text — used by future P3.1.

    Tolerant to surrounding prose / fenced code blocks / leading-text noise.
    Returns ``None`` if no valid JSON object is found.
    """
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
