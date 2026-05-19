# -*- coding: utf-8 -*-
"""User research profile — L1/L2/L3 memory for research direction preferences."""

from __future__ import annotations

import json
import logging
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from literature_assistant.core.models.research_profile import (
    ResearchProfile,
    ResearchDirection,
    ResearchFact,
)

logger = logging.getLogger(__name__)

_PROFILE_FILENAME = "user_research_profile.json"


def _profile_path(runtime_state: Path) -> Path:
    return runtime_state / _PROFILE_FILENAME


def load_profile(runtime_state: Path) -> ResearchProfile:
    """Load or initialize the research profile."""
    path = _profile_path(runtime_state)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ResearchProfile(**data)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Corrupt research profile, reinitializing: %s", exc)
    return ResearchProfile()


def save_profile(profile: ResearchProfile, runtime_state: Path) -> None:
    """Persist research profile atomically."""
    path = _profile_path(runtime_state)
    runtime_state.mkdir(parents=True, exist_ok=True)
    profile.updated = datetime.now(UTC)
    payload = profile.model_dump(mode="json")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def add_direction(profile: ResearchProfile, keyword: str, weight: float = 1.0, description: str = "") -> ResearchProfile:
    """Add or update a research direction (L1). Dedup by keyword."""
    existing = {d.keyword.lower(): d for d in profile.directions}
    kw_lower = keyword.lower()
    if kw_lower in existing:
        d = existing[kw_lower]
        d.weight = min(5.0, d.weight + weight * 0.5)
        d.last_used = datetime.now(UTC)
        if description:
            d.description = description
    else:
        profile.directions.append(ResearchDirection(
            keyword=keyword, weight=weight,
            description=description, last_used=datetime.now(UTC),
        ))
    # Keep L1 ≤ 50 entries, prune lowest weight
    if len(profile.directions) > 50:
        profile.directions.sort(key=lambda d: d.weight)
        profile.directions = profile.directions[-50:]
    return profile


def add_fact(profile: ResearchProfile, category: str, value: str, confidence: float = 0.5) -> ResearchProfile:
    """Add a research fact (L2). Dedup by category+value."""
    key = (category.lower(), value.lower()[:100])
    exists = any(
        (f.category.lower(), f.value.lower()[:100]) == key
        for f in profile.facts
    )
    if not exists:
        profile.facts.append(ResearchFact(
            category=category, value=value, confidence=confidence,
        ))
    return profile


def extract_keywords(text: str, profile: ResearchProfile) -> list[str]:
    """Extract research-relevant keywords from a conversation turn.

    Simple heuristic: match known directions + common academic pattern.
    Respects the 'no LLM writes memory' rule — rule-based only.
    """
    keywords: list[str] = []
    text_lower = text.lower()

    # Boost existing directions mentioned in text
    for d in profile.directions:
        if d.keyword.lower() in text_lower:
            keywords.append(d.keyword)

    # Common academic domain indicators (rule-based extraction)
    domain_patterns = [
        "nlp", "自然语言处理", "machine learning", "深度学习",
        "因果推断", "causal inference", "数值模拟", "numerical simulation",
        "焊接", "welding", "finite element", "有限元", "fluid dynamics",
        "computational", "计算", "统计", "statistical", "实验", "experimental",
        "review", "综述", "meta-analysis", "元分析", "systematic review",
        "neural network", "神经网络", "transformer", "bert", "gpt",
        "reinforcement learning", "强化学习", "computer vision", "计算机视觉",
    ]
    for pattern in domain_patterns:
        if pattern in text_lower and pattern not in [k.lower() for k in keywords]:
            keywords.append(pattern)

    return keywords


def get_boost_keywords(profile: ResearchProfile, limit: int = 5) -> list[str]:
    """Return top-N weighted research direction keywords for retrieval boost."""
    active = [d for d in profile.directions if d.weight > 0.5]
    active.sort(key=lambda d: d.weight, reverse=True)
    return [d.keyword for d in active[:limit]]


def get_research_context_string(profile: ResearchProfile) -> str | None:
    """Build a concise context string for injection into prompts/queries."""
    directions = get_boost_keywords(profile)
    if not directions:
        return None
    parts = [f"研究方向: {', '.join(directions)}"]

    # Add key terminology facts
    term_facts = [
        f.value for f in profile.facts
        if f.category == "terminology" and f.confidence > 0.3
    ][:5]
    if term_facts:
        parts.append(f"术语: {'; '.join(term_facts)}")

    return " | ".join(parts)