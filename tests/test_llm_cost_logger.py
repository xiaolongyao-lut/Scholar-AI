from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import llm_cost_logger


def _patch_log_destination(monkeypatch, tmp_path: Path) -> Path:
    log_file = tmp_path / "llm_cost.jsonl"
    monkeypatch.setattr(llm_cost_logger, "_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(llm_cost_logger, "_LOG_FILE", log_file)
    return log_file


def test_log_llm_call_writes_one_complete_json_row(tmp_path, monkeypatch) -> None:
    log_file = _patch_log_destination(monkeypatch, tmp_path)
    monkeypatch.delenv("LLM_COST_TELEMETRY", raising=False)

    llm_cost_logger.log_llm_call(
        model="qwen-max",
        task="extraction",
        prompt_tokens=123,
        completion_tokens=45,
        latency_ms=845.234,
    )

    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    row = json.loads(lines[0])
    assert set(row) == {
        "ts",
        "model",
        "task",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cost_usd",
        "latency_ms",
        "status",
        "pricing_known",
        "cache_status",
        "decision",
    }
    datetime.fromisoformat(row["ts"])
    assert row["model"] == "qwen-max"
    assert row["task"] == "extraction"
    assert row["prompt_tokens"] == 123
    assert row["completion_tokens"] == 45
    assert row["total_tokens"] == 168
    assert row["latency_ms"] == 845.23
    assert row["status"] == "ok"
    assert row["pricing_known"] is True
    assert row["cache_status"] == "miss"
    assert row["decision"] == "invoke"


def test_log_llm_call_skips_writes_when_telemetry_env_is_zero(tmp_path, monkeypatch) -> None:
    log_file = _patch_log_destination(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_COST_TELEMETRY", "0")

    llm_cost_logger.log_llm_call(
        model="qwen-max",
        task="chat",
        prompt_tokens=1,
        completion_tokens=1,
        latency_ms=1.0,
    )

    assert not log_file.exists()


def test_log_llm_call_skips_writes_when_telemetry_env_is_off(tmp_path, monkeypatch) -> None:
    log_file = _patch_log_destination(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_COST_TELEMETRY", "off")

    llm_cost_logger.log_llm_call(
        model="qwen-max",
        task="chat",
        prompt_tokens=1,
        completion_tokens=1,
        latency_ms=1.0,
    )

    assert not log_file.exists()


def test_log_llm_call_writes_unknown_model_with_pricing_known_false(tmp_path, monkeypatch) -> None:
    log_file = _patch_log_destination(monkeypatch, tmp_path)
    monkeypatch.delenv("LLM_COST_TELEMETRY", raising=False)

    llm_cost_logger.log_llm_call(
        model="unknown-model",
        task="rewrite",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=10.0,
    )

    row = json.loads(log_file.read_text(encoding="utf-8").splitlines()[0])
    assert row["model"] == "unknown-model"
    assert row["pricing_known"] is False


def test_log_llm_call_writes_explicit_cache_and_decision_fields(tmp_path, monkeypatch) -> None:
    log_file = _patch_log_destination(monkeypatch, tmp_path)
    monkeypatch.delenv("LLM_COST_TELEMETRY", raising=False)

    llm_cost_logger.log_llm_call(
        model="qwen-max",
        task="chat",
        prompt_tokens=10,
        completion_tokens=2,
        latency_ms=9.5,
        cache_status="hit_mem",
        decision="skip",
    )

    row = json.loads(log_file.read_text(encoding="utf-8").splitlines()[0])
    assert row["cache_status"] == "hit_mem"
    assert row["decision"] == "skip"


def test_log_llm_call_keeps_error_rows_observable_with_zero_usage(tmp_path, monkeypatch) -> None:
    log_file = _patch_log_destination(monkeypatch, tmp_path)
    monkeypatch.delenv("LLM_COST_TELEMETRY", raising=False)

    llm_cost_logger.log_llm_call(
        model="qwen-max",
        task="chat",
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=12.0,
        status="error",
    )

    row = json.loads(log_file.read_text(encoding="utf-8").splitlines()[0])
    assert row["status"] == "error"
    assert row["prompt_tokens"] == 0
    assert row["completion_tokens"] == 0
    assert row["total_tokens"] == 0
    assert row["cost_usd"] == 0.0
    assert row["cache_status"] == "miss"
    assert row["decision"] == "invoke"


def test_log_llm_call_swallows_io_errors(tmp_path, monkeypatch) -> None:
    _patch_log_destination(monkeypatch, tmp_path)
    monkeypatch.delenv("LLM_COST_TELEMETRY", raising=False)

    class _BrokenPath:
        def open(self, *args, **kwargs):
            raise OSError("disk full")

    monkeypatch.setattr(llm_cost_logger, "_LOG_FILE", _BrokenPath())

    llm_cost_logger.log_llm_call(
        model="qwen-max",
        task="chat",
        prompt_tokens=1,
        completion_tokens=1,
        latency_ms=1.0,
    )
