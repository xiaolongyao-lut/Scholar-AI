# -*- coding: utf-8 -*-
"""Tests for the chart_metrics JSONL collector (P3.1c)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = REPO_ROOT / "literature_assistant" / "core"
if str(CORE_PATH) not in sys.path:
    sys.path.insert(0, str(CORE_PATH))


def _redirect_metrics(monkeypatch, tmp_path: Path) -> Path:
    """Redirect chart_metrics file path to tmp_path. Returns expected file."""
    target = tmp_path / "chart_intent_metrics.jsonl"
    from agents import chart_metrics

    monkeypatch.setattr(chart_metrics, "_metrics_path", lambda: target)
    return target


def test_record_event_writes_jsonl_line(tmp_path, monkeypatch) -> None:
    target = _redirect_metrics(monkeypatch, tmp_path)
    from agents.chart_metrics import record_event

    record_event("intent_seed_match", "draw 柱状图 of laser power", extra={"seed": "柱状图"})
    assert target.is_file()
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "intent_seed_match"
    assert payload["query_hash"] is not None and len(payload["query_hash"]) == 12
    # Privacy: query body (not the matched seed itself) must not appear.
    # The seed is dictionary-known metadata; "laser power" / "draw of"
    # are user content and must be redacted.
    assert "laser power" not in lines[0]
    assert "draw" not in lines[0]
    assert payload["query_len"] == len("draw 柱状图 of laser power")
    assert payload["seed"] == "柱状图"


def test_record_event_silently_drops_unknown_event(tmp_path, monkeypatch) -> None:
    target = _redirect_metrics(monkeypatch, tmp_path)
    from agents.chart_metrics import record_event

    record_event("not_a_real_event", "q")  # type: ignore[arg-type]
    assert not target.exists()


def test_record_event_appends_in_order(tmp_path, monkeypatch) -> None:
    target = _redirect_metrics(monkeypatch, tmp_path)
    from agents.chart_metrics import read_events, record_event

    record_event("intent_seed_match", "q1")
    record_event("spec_success", "q1", extra={"series_types": ["bar"]})
    record_event("spec_invalid_json", "q2", extra={"answer_len": 0})

    events = read_events()
    assert [e["event"] for e in events] == [
        "intent_seed_match",
        "spec_success",
        "spec_invalid_json",
    ]
    assert events[1]["series_types"] == ["bar"]


def test_record_event_survives_io_failure(tmp_path, monkeypatch) -> None:
    """Metrics write failure must NOT propagate to the caller."""
    from agents import chart_metrics

    monkeypatch.setattr(
        chart_metrics, "_metrics_path", lambda: tmp_path / "nope" / "deep" / "x.jsonl"
    )
    # Make mkdir raise to simulate truly broken write path
    original_mkdir = Path.mkdir

    def _raise_mkdir(self, *args, **kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(Path, "mkdir", _raise_mkdir)
    try:
        chart_metrics.record_event("intent_seed_match", "q")
    except Exception:  # noqa: BLE001
        raise AssertionError("record_event must swallow I/O errors")
    finally:
        monkeypatch.setattr(Path, "mkdir", original_mkdir)


def test_intent_seed_match_emits_metric(tmp_path, monkeypatch) -> None:
    target = _redirect_metrics(monkeypatch, tmp_path)
    from agents.intent_detector import detect_chart_intent
    from agents.chart_metrics import read_events

    assert detect_chart_intent("draw a bar chart") == "chart"
    events = read_events()
    assert len(events) == 1
    assert events[0]["event"] == "intent_seed_match"
    assert events[0]["seed"] == "bar chart"


def test_intent_no_match_emits_no_metric(tmp_path, monkeypatch) -> None:
    target = _redirect_metrics(monkeypatch, tmp_path)
    from agents.intent_detector import detect_chart_intent
    from agents.chart_metrics import read_events

    assert detect_chart_intent("summarize the methods section") == "text"
    assert read_events() == []


def test_intent_llm_match_emits_metric(tmp_path, monkeypatch) -> None:
    import asyncio

    target = _redirect_metrics(monkeypatch, tmp_path)
    from agents.intent_detector import detect_chart_intent_via_llm
    from agents.chart_metrics import read_events

    async def _caller(_p, _c):
        return "chart"

    decision = asyncio.run(detect_chart_intent_via_llm("show data", _caller))
    assert decision == "chart"
    events = read_events()
    assert any(e["event"] == "intent_llm_match" for e in events)


def test_intent_llm_no_emits_metric(tmp_path, monkeypatch) -> None:
    import asyncio

    target = _redirect_metrics(monkeypatch, tmp_path)
    from agents.intent_detector import detect_chart_intent_via_llm
    from agents.chart_metrics import read_events

    async def _caller(_p, _c):
        return "text"

    decision = asyncio.run(detect_chart_intent_via_llm("summarize methods", _caller))
    assert decision == "text"
    events = read_events()
    assert any(e["event"] == "intent_llm_no" for e in events)


def test_intent_llm_error_emits_metric(tmp_path, monkeypatch) -> None:
    import asyncio

    target = _redirect_metrics(monkeypatch, tmp_path)
    from agents.intent_detector import detect_chart_intent_via_llm
    from agents.chart_metrics import read_events

    async def _failing(_p, _c):
        raise RuntimeError("provider down")

    decision = asyncio.run(detect_chart_intent_via_llm("any query", _failing))
    assert decision == "text"
    events = read_events()
    error_events = [e for e in events if e["event"] == "intent_llm_error"]
    assert len(error_events) == 1
    assert error_events[0]["error"] == "RuntimeError"


def test_chart_spec_success_emits_metric(tmp_path, monkeypatch) -> None:
    import asyncio

    target = _redirect_metrics(monkeypatch, tmp_path)
    from agents.chart_agent import generate_chart_spec
    from agents.chart_metrics import read_events

    async def _caller(_p, _c):
        return '{"series":[{"type":"bar","data":[1,2]}]}'

    spec = asyncio.run(generate_chart_spec("q", [{"source": "x"}], chat_caller=_caller))
    assert spec is not None
    events = read_events()
    success = [e for e in events if e["event"] == "spec_success"]
    assert len(success) == 1
    assert success[0]["series_types"] == ["bar"]


def test_chart_spec_invalid_json_emits_metric(tmp_path, monkeypatch) -> None:
    import asyncio

    target = _redirect_metrics(monkeypatch, tmp_path)
    from agents.chart_agent import generate_chart_spec
    from agents.chart_metrics import read_events

    async def _caller(_p, _c):
        return "Sorry, I cannot draw charts."

    asyncio.run(generate_chart_spec("q", [{"source": "x"}], chat_caller=_caller))
    events = read_events()
    assert any(e["event"] == "spec_invalid_json" for e in events)


def test_chart_spec_sanitizer_reject_emits_metric(tmp_path, monkeypatch) -> None:
    import asyncio

    target = _redirect_metrics(monkeypatch, tmp_path)
    from agents.chart_agent import generate_chart_spec
    from agents.chart_metrics import read_events

    async def _caller(_p, _c):
        return '{"title":{"text":"no series"}}'

    asyncio.run(generate_chart_spec("q", [{"source": "x"}], chat_caller=_caller))
    events = read_events()
    rejects = [e for e in events if e["event"] == "spec_sanitizer_reject"]
    assert len(rejects) == 1
    assert "title" in rejects[0]["top_keys"]


def test_chart_spec_llm_error_emits_metric(tmp_path, monkeypatch) -> None:
    import asyncio

    target = _redirect_metrics(monkeypatch, tmp_path)
    from agents.chart_agent import generate_chart_spec
    from agents.chart_metrics import read_events

    async def _failing(_p, _c):
        raise TimeoutError("upstream timed out")

    asyncio.run(generate_chart_spec("q", [{"source": "x"}], chat_caller=_failing))
    events = read_events()
    errors = [e for e in events if e["event"] == "spec_llm_error"]
    assert len(errors) == 1
    assert errors[0]["error"] == "TimeoutError"
