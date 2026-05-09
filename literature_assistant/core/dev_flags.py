# -*- coding: utf-8 -*-
"""Centralized dev-only feature flags.

Single source of truth for ``LITERATURE_DEV_MODE``. Routers that expose
debug or developer-only behavior should call ``is_dev_mode_enabled()``
rather than re-reading the env var directly.
"""

from __future__ import annotations

import os


_TRUTHY = {"1", "true", "yes", "on"}


def is_dev_mode_enabled() -> bool:
    """Return True when ``LITERATURE_DEV_MODE`` is set to a truthy value.

    Production default is off. When off, sensitive debug fields such as
    full prompt templates must not be returned over the wire.
    """
    return str(os.environ.get("LITERATURE_DEV_MODE") or "").strip().lower() in _TRUTHY


def is_chart_agent_enabled() -> bool:
    """Return True when ``LITERATURE_ENABLE_CHART_AGENT`` is truthy.

    Default off. When off, the Intelligent Chat router must skip intent
    detection and always return text answers.
    """
    return str(os.environ.get("LITERATURE_ENABLE_CHART_AGENT") or "").strip().lower() in _TRUTHY


def is_chart_agent_llm_intent_enabled() -> bool:
    """Return True when ``LITERATURE_ENABLE_CHART_AGENT_LLM_INTENT`` is truthy.

    Reserved for P3.1: gates the cost-bearing LLM intent fallback. Default off.
    """
    return (
        str(os.environ.get("LITERATURE_ENABLE_CHART_AGENT_LLM_INTENT") or "").strip().lower()
        in _TRUTHY
    )
