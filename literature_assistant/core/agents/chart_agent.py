# -*- coding: utf-8 -*-
"""ChartAgent — produce a sanitized ECharts spec via LLM call.

Pattern adapted from RAG-Pro ``backend/app/agents/chart_agent.py``: prompt
the LLM for a JSON ECharts option, extract the JSON, then strictly
allowlist option fields. Anything not on the allowlist (functions, HTML
strings, event handlers, raw JS) is discarded so the frontend can safely
pass the spec into ``ReactECharts``.

P3.1a (2026-05-09): replaced the placeholder spec with a real LLM call.
The caller injects ``chat_caller`` so this module stays decoupled from
the Intelligent Chat router and tests can drop in a fake.

Failure semantics: every error path returns ``None`` so the caller falls
back to a plain text response — never crash the chat handler over a chart.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Mapping


_logger = logging.getLogger("ChartAgent")

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

_CONTEXT_PREVIEW_CHARS = 600
_MAX_CONTEXT_CHUNKS = 8

ChatCaller = Callable[[str, list[str]], Awaitable[str]]


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


def parse_llm_chart_json(text: str) -> dict[str, Any] | None:
    """Extract a JSON object from raw LLM text.

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


def _build_context_strings(chunks: list[dict[str, Any]]) -> list[str]:
    """Compress chunks into short prompt-friendly strings."""
    lines: list[str] = []
    for idx, chunk in enumerate(chunks[:_MAX_CONTEXT_CHUNKS]):
        source = str(chunk.get("source") or f"chunk-{idx}")
        content = str(chunk.get("content") or "")
        if len(content) > _CONTEXT_PREVIEW_CHARS:
            content = content[: _CONTEXT_PREVIEW_CHARS - 1].rstrip() + "…"
        lines.append(f"[{idx + 1}] source={source}\n{content}")
    return lines


def _build_chart_prompt(query: str, context_strings: list[str]) -> str:
    """Compose a prompt that asks the LLM for a JSON-only ECharts option.

    The prompt names the allowlist explicitly so the model is less likely to
    emit fields the sanitizer would discard. Reply must be JSON only — no
    fences, no prose — but ``parse_llm_chart_json`` tolerates leading text
    just in case.
    """
    allowed_top = ", ".join(sorted(_ALLOWED_TOP_LEVEL_KEYS))
    allowed_series = ", ".join(sorted(_ALLOWED_SERIES_TYPES))
    context_block = "\n\n".join(context_strings) if context_strings else "(no context)"
    return (
        "You generate ECharts option objects as JSON. Given the question and the "
        "literature context, output a single valid JSON object describing one chart.\n"
        "\n"
        "Hard requirements (your output is post-validated; non-conforming fields will be dropped):\n"
        f"- Top-level keys must be from: {allowed_top}.\n"
        f"- Each item in `series` must have `type` from {{{allowed_series}}} and a `data` array.\n"
        "- Do NOT include `formatter`, `renderer`, `rich`, or `html` keys.\n"
        "- Do NOT include function strings or HTML.\n"
        "- Reply with ONLY the JSON object — no markdown fences, no commentary.\n"
        "\n"
        f"Question: {query}\n"
        "\n"
        "Context:\n"
        f"{context_block}\n"
        "\n"
        "JSON:\n"
    )


async def generate_chart_spec(
    query: str,
    chunks: list[dict[str, Any]],
    chat_caller: ChatCaller,
) -> dict[str, Any] | None:
    """Generate a sanitized ECharts spec via LLM.

    Args:
        query: The user's natural-language chart request.
        chunks: Context chunks with ``source`` and ``content`` fields
            (typically ``ContextChunkPayload.model_dump()``).
        chat_caller: Awaitable ``(prompt, context) -> answer_text``.
            Caller injects so this module never reaches into the chat
            router for the LLM config or test monkeypatches.

    Returns:
        A sanitized ECharts option dict, or ``None`` if the LLM call,
        JSON extraction, or sanitizer rejected the candidate. Callers
        should fall back to a plain text response on ``None``.
    """
    context_strings = _build_context_strings(chunks)
    prompt = _build_chart_prompt(query, context_strings)
    try:
        raw_answer = await chat_caller(prompt, context_strings)
    except Exception as exc:  # noqa: BLE001 — chart never breaks chat
        _logger.warning("chart_agent: chat_caller raised: %s", exc)
        return None
    parsed = parse_llm_chart_json(raw_answer or "")
    if parsed is None:
        _logger.info("chart_agent: LLM did not return valid JSON")
        return None
    sanitized = sanitize_echarts_option(parsed)
    if sanitized is None:
        _logger.info("chart_agent: sanitizer rejected LLM spec")
        return None
    return sanitized
