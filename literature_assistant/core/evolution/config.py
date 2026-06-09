"""
Lightweight reader for the `evolution:` section of rag_integration_config.yaml.

Used by capture sites (inspiration / discussion / runtime / skill routers) to
honor evolution kill switches without each route re-implementing YAML
parsing. The reader is intentionally not cached — config edits during dogfood
should be picked up on the next call without needing a process restart.

Kill switches:
    recall_enabled              — recall context
    candidate_capture_enabled   — capture writes
    review_ui_enabled           — inbox visibility
    promotion_enabled           — MemPalace promotion
    curator_enabled             — background curator
    curator_interval_seconds    — minimum interval between scheduled passes
    curator_llm_judge_enabled   — LLM-judged semantic conflict
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

import yaml

logger = logging.getLogger("EvolutionConfig")

_CORE_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _CORE_ROOT / "config" / "rag_integration_config.yaml"


def load_evolution_config() -> Dict[str, Any]:
    """Return the `evolution:` mapping from rag_integration_config.yaml.

    Missing file or missing section returns an empty dict so callers can use
    `.get(key, default)` without further guards.
    """

    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as fp:
            parsed = yaml.safe_load(fp) or {}
    except FileNotFoundError:
        logger.warning(
            "rag_integration_config.yaml missing at %s; evolution section defaulted to off",
            _CONFIG_PATH,
        )
        return {}
    except yaml.YAMLError as exc:
        logger.warning("rag_integration_config.yaml parse error: %s; treating evolution as off", exc)
        return {}

    section = parsed.get("evolution") if isinstance(parsed, dict) else None
    return section if isinstance(section, dict) else {}


def _feature_flag_value(name: str, fallback: bool) -> bool:
    try:
        from feature_flags import FEATURE_FLAGS, is_enabled
    except Exception:
        return fallback
    if name not in FEATURE_FLAGS:
        return fallback
    return bool(is_enabled(name))


def is_candidate_capture_enabled() -> bool:
    """True when capture routes may persist candidates."""

    fallback = bool(load_evolution_config().get("candidate_capture_enabled", True))
    return _feature_flag_value("evolution_candidate_capture", fallback)


def is_review_ui_enabled() -> bool:
    """True when the review inbox should be visible in the UI."""

    fallback = bool(load_evolution_config().get("review_ui_enabled", False))
    return _feature_flag_value("evolution_review_ui", fallback)


def is_recall_enabled() -> bool:
    """True when recall paths may pull context before generation."""

    return bool(load_evolution_config().get("recall_enabled", False))


def is_promotion_enabled() -> bool:
    """True when /promote may write to MemPalace and record skill drafts."""

    fallback = bool(load_evolution_config().get("promotion_enabled", False))
    return _feature_flag_value("evolution_promotion", fallback)


def is_curator_enabled() -> bool:
    """True when /curate/run may transition pending candidates."""

    return bool(load_evolution_config().get("curator_enabled", False))


def curator_interval_seconds() -> int:
    """Return the scheduled curator interval with a defensive lower bound."""
    raw_value = load_evolution_config().get("curator_interval_seconds", 3600)
    try:
        interval = int(raw_value)
    except (TypeError, ValueError):
        return 3600
    return max(60, interval)


def is_curator_llm_judge_enabled() -> bool:
    """True when curator conflict sweep may call the LLM judge.

    Independent of `curator_enabled`; both must be true for the judge to
    run. Default false so any environment without LLM credentials behaves
    exactly like the pre-Opt-§5 structural-only curator.
    """

    return bool(load_evolution_config().get("curator_llm_judge_enabled", False))
