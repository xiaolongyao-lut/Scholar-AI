# -*- coding: utf-8 -*-
"""Deterministic chart-intent detection for the Intelligent Chat router.

Why:
    P3 spike (per ``docs/plans/active/2026-05-09-rag-pro-borrow-features.md``)
    needs cheap intent routing before LLM generation. Seed words borrowed
    verbatim from RAG-Pro to keep the rule simple and reversible.

Future P3.1 (gated by ``LITERATURE_ENABLE_CHART_AGENT_LLM_INTENT``) may add
LLM-based intent for borderline queries; not enabled in this spike.
"""

from __future__ import annotations

from typing import Literal

ChartIntent = Literal["text", "chart"]

_CHART_SEED_WORDS: tuple[str, ...] = (
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


def detect_chart_intent(query: str) -> ChartIntent:
    """Return ``chart`` if query contains any seed word, else ``text``."""
    if not query:
        return "text"
    text = query.lower()
    for word in _CHART_SEED_WORDS:
        if word.lower() in text:
            return "chart"
    return "text"
