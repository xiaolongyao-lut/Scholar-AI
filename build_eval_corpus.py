# -*- coding: utf-8 -*-
"""Compatibility constants for local eval-corpus audit tests."""

from __future__ import annotations

QUERY_TEMPLATES: dict[str, list[str]] = {
    "simple": [
        "{topic}的最新研究进展",
        "{topic}的主要工艺参数",
        "{topic}的性能影响因素",
    ],
    "medium": [
        "{topic}与力学性能之间的关系研究",
        "{topic}对组织演化的影响机制",
        "{topic}在增材制造中的应用比较",
    ],
    "hard": [
        "{topic}在{topic2}条件下对{topic3}的耦合效应分析",
        "{topic}、{topic2}与{topic3}之间的多因素交互机制",
    ],
}
