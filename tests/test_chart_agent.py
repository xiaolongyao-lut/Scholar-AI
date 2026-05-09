# -*- coding: utf-8 -*-
"""Unit tests for ChartAgent sanitizer + intent detector (P3 spike)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = REPO_ROOT / "literature_assistant" / "core"
if str(CORE_PATH) not in sys.path:
    sys.path.insert(0, str(CORE_PATH))

from agents.chart_agent import (
    generate_chart_spec,
    parse_llm_chart_json,
    sanitize_echarts_option,
)
from agents.intent_detector import detect_chart_intent


def test_intent_detector_picks_up_seed_words() -> None:
    assert detect_chart_intent("帮我画一个柱状图") == "chart"
    assert detect_chart_intent("做一个趋势分布对比") == "chart"


def test_intent_detector_defaults_to_text() -> None:
    assert detect_chart_intent("总结一下这篇论文的方法") == "text"
    assert detect_chart_intent("") == "text"


def test_intent_detector_picks_up_english_seeds() -> None:
    """Live smoke regression: English-only KB queries must trigger chart too."""
    assert detect_chart_intent("draw a bar chart of laser power") == "chart"
    assert detect_chart_intent("Show me the histogram") == "chart"
    assert detect_chart_intent("plot the distribution") == "chart"
    assert detect_chart_intent("Visualize this data") == "chart"


def test_intent_detector_english_word_boundary_safety() -> None:
    """English seeds must use word boundaries — 'chart' must not match 'discharge'."""
    assert detect_chart_intent("discharge the capacitor") == "text"
    assert detect_chart_intent("uncharted territory") == "text"
    assert detect_chart_intent("photograph the sample") == "text"
    assert detect_chart_intent("paragraph two summarizes") == "text"


def test_sanitizer_drops_function_strings() -> None:
    raw = {
        "title": {"text": "demo"},
        "xAxis": {"type": "category", "data": ["a", "b"]},
        "yAxis": {"type": "value"},
        "tooltip": {"formatter": "function(p){return p.value}"},
        "series": [{"type": "bar", "data": [1, 2]}],
    }
    safe = sanitize_echarts_option(raw)
    assert safe is not None
    # tooltip kept but formatter dropped
    assert "formatter" not in (safe.get("tooltip") or {})


def test_sanitizer_rejects_invalid_series() -> None:
    raw = {"series": [{"type": "html-injection", "data": [1]}]}
    assert sanitize_echarts_option(raw) is None


def test_sanitizer_requires_series() -> None:
    assert sanitize_echarts_option({"title": {"text": "x"}}) is None


def test_sanitizer_rejects_html_strings() -> None:
    raw = {
        "title": {"text": "<script>alert(1)</script>"},
        "series": [{"type": "bar", "data": [1, 2]}],
    }
    safe = sanitize_echarts_option(raw)
    assert safe is not None
    title = safe.get("title") or {}
    assert "text" not in title or not str(title.get("text", "")).startswith("<")


def test_generate_chart_spec_returns_safe_option() -> None:
    chunks = [{"source": "paper-1.pdf"}, {"source": "paper-2.pdf"}]
    spec = generate_chart_spec("画一个柱状图比较两篇论文", chunks)
    assert spec is not None
    assert spec["series"][0]["type"] == "bar"


def test_parse_llm_chart_json_handles_fenced_text() -> None:
    raw = "Sure, here is the spec:\n```json\n{\"series\":[{\"type\":\"bar\",\"data\":[1]}]}\n```"
    parsed = parse_llm_chart_json(raw)
    assert parsed is not None
    assert parsed["series"][0]["type"] == "bar"


def test_parse_llm_chart_json_returns_none_on_garbage() -> None:
    assert parse_llm_chart_json("no json here") is None
    assert parse_llm_chart_json("{not valid json}") is None
