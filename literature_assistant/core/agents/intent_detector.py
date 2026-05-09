# -*- coding: utf-8 -*-
"""Deterministic chart-intent detection for the Intelligent Chat router.

Why:
    P3 spike (per ``docs/plans/active/2026-05-09-rag-pro-borrow-features.md``)
    needs cheap intent routing before LLM generation. Seed words borrowed
    verbatim from RAG-Pro to keep the rule simple and reversible. English
    seeds added 2026-05-09 after live smoke showed bilingual queries
    (English doc + Chinese query) failed retrieval; users mixing languages
    or working in English-only KBs should still trigger chart routing.

Future P3.1 (gated by ``LITERATURE_ENABLE_CHART_AGENT_LLM_INTENT``) may add
LLM-based intent for borderline queries; not enabled in this spike.
"""

from __future__ import annotations

import re
from typing import Literal

ChartIntent = Literal["text", "chart"]

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
    for word in _CHART_SEED_WORDS_CN:
        if word in text:
            return "chart"
    if _EN_PATTERN.search(text):
        return "chart"
    return "text"
