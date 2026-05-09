# -*- coding: utf-8 -*-
"""Deterministic + optional-LLM chart-intent detection.

Why:
    P3 spike (per ``docs/plans/active/2026-05-09-rag-pro-borrow-features.md``)
    needs cheap intent routing before LLM generation. Seed words borrowed
    verbatim from RAG-Pro to keep the rule simple and reversible. English
    seeds added 2026-05-09 after live smoke showed bilingual queries
    (English doc + Chinese query) failed retrieval; users mixing languages
    or working in English-only KBs should still trigger chart routing.

P3.1b (2026-05-09): added ``detect_chart_intent_via_llm`` for the
borderline case where seed regex misses but the user still asked for a
chart. Gated by ``LITERATURE_ENABLE_CHART_AGENT_LLM_INTENT`` so cost
stays opt-in. Any LLM failure returns ``text`` (safe default).
"""

from __future__ import annotations

import logging
import re
from typing import Awaitable, Callable, Literal


_logger = logging.getLogger("ChartIntent")

ChartIntent = Literal["text", "chart"]

ChatCaller = Callable[[str, list[str]], Awaitable[str]]

_CHART_SEED_WORDS_CN: tuple[str, ...] = (
    "图表",
    "折线图",
    "柱状图",
    "饼图",
    "可视化",
    "趋势",
    "分布",
    "对比",
    "统计",
)

# English seeds restricted to explicit visualization vocabulary so that
# common verbs like "compare" or "trend" don't over-trigger. Word-boundary
# regex prevents 'chart' matching mid-word substrings like 'discharge'.
_CHART_SEED_WORDS_EN: tuple[str, ...] = (
    "chart",
    "plot",
    "graph",
    "histogram",
    "bar chart",
    "line chart",
    "pie chart",
    "scatter plot",
    "visualize",
    "visualisation",
    "visualization",
)

_EN_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _CHART_SEED_WORDS_EN) + r")\b",
    re.IGNORECASE,
)


def detect_chart_intent(query: str) -> ChartIntent:
    """Return ``chart`` if query contains any seed word, else ``text``.

    Chinese seeds use substring match (CJK has no word boundaries in regex).
    English seeds use word-boundary match to avoid mid-word false positives.
    """
    if not query:
        return "text"
    text = query.lower()
    matched_seed: str | None = None
    for word in _CHART_SEED_WORDS_CN:
        if word in text:
            matched_seed = word
            break
    if matched_seed is None:
        match = _EN_PATTERN.search(text)
        if match is not None:
            matched_seed = match.group(0)
    if matched_seed is not None:
        from agents import chart_metrics  # local import to avoid cycles
        chart_metrics.record_event(
            "intent_seed_match", query, extra={"seed": matched_seed}
        )
        return "chart"
    return "text"


_LLM_INTENT_PROMPT = (
    "You are a binary intent classifier. Decide whether the user's question "
    "asks for a chart, plot, visualization, or any graphical figure of data.\n"
    "\n"
    "Reply with EXACTLY one lowercase word: `chart` or `text`. No punctuation, "
    "no explanation.\n"
    "\n"
    "Examples:\n"
    "Question: How does laser power affect hardness? → text\n"
    "Question: Show me a comparison of yields by year. → chart\n"
    "Question: Summarize the methods. → text\n"
    "Question: 比较一下2020和2021的数据 → chart\n"
    "\n"
    "Question: {query}\n"
    "\n"
    "Reply:"
)


def _normalize_llm_intent(reply: str) -> ChartIntent:
    """Coerce the LLM's free-form reply into a strict ChartIntent.

    Robust to leading/trailing whitespace, punctuation, and case. Anything
    not unambiguously "chart" returns "text" — false positives are worse
    than false negatives because chart_agent then burns another LLM call.
    """
    if not reply:
        return "text"
    cleaned = reply.strip().lower()
    tokens = cleaned.split()
    if not tokens:
        return "text"
    first = tokens[0].strip(".,!?:;\"'`()[]{}")
    if first == "chart":
        return "chart"
    return "text"


async def detect_chart_intent_via_llm(
    query: str,
    chat_caller: ChatCaller,
) -> ChartIntent:
    """LLM-driven intent fallback. Caller should only invoke this when
    deterministic ``detect_chart_intent`` returned ``text`` AND the
    ``LITERATURE_ENABLE_CHART_AGENT_LLM_INTENT`` flag is on.

    Args:
        query: User's natural-language question.
        chat_caller: Awaitable ``(prompt, context) -> answer`` reused from
            the same provider chain as the main chat router. Tests inject
            a fake to avoid real LLM calls.

    Returns:
        ``"chart"`` only when the LLM unambiguously says "chart". All
        other replies and any exception coalesce to ``"text"`` so cost
        stays bounded and a misclassified error never spawns a chart
        spec call.
    """
    if not query:
        return "text"
    from agents import chart_metrics  # local import to avoid cycles

    prompt = _LLM_INTENT_PROMPT.format(query=query)
    try:
        reply = await chat_caller(prompt, [])
    except Exception as exc:  # noqa: BLE001 — intent fallback never breaks chat
        _logger.warning("intent_detector: LLM call raised: %s", exc)
        chart_metrics.record_event(
            "intent_llm_error", query, extra={"error": exc.__class__.__name__}
        )
        return "text"
    decision = _normalize_llm_intent(reply or "")
    chart_metrics.record_event(
        "intent_llm_match" if decision == "chart" else "intent_llm_no",
        query,
        extra={"reply_preview": (reply or "")[:60]},
    )
    return decision
