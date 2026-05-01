from __future__ import annotations

import importlib
import json
import sys
import types
from hashlib import sha256
from pathlib import Path

import pytest

from layers import ai_adapter as ai_mod
from layers.ai_adapter import AIAdapter


class _FakeResponse:
    def __init__(self, content: str = "{}", prompt_tokens: int = 11, completion_tokens: int = 7):
        self.choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=content))]
        self.usage = types.SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )


class _FakeCompletions:
    def __init__(self, response: _FakeResponse):
        self.calls: list[dict] = []
        self._response = response

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FailingCompletions:
    def create(self, **kwargs):
        raise RuntimeError("vendor failed")


def _make_adapter(response: _FakeResponse) -> tuple[AIAdapter, _FakeCompletions]:
    adapter = object.__new__(AIAdapter)
    completions = _FakeCompletions(response)
    adapter.client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))
    adapter.model = "qwen-max"
    adapter.enabled = True
    return adapter, completions


def _load_gateway():
    if "model_call_gateway" in sys.modules:
        return importlib.reload(sys.modules["model_call_gateway"])
    return importlib.import_module("model_call_gateway")


def _prompt_hash(prompt: str) -> str:
    return sha256(prompt.encode("utf-8")).hexdigest()


def _sampling_hash(payload: dict[str, object]) -> str:
    material = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(material.encode("utf-8")).hexdigest()


@pytest.fixture
def gateway_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MODEL_CALL_GATEWAY_CACHE_DIR", str(output_dir / "gateway_cache"))
    monkeypatch.setenv("MODEL_CALL_GATEWAY_METRICS_PATH", str(output_dir / "gateway_metrics.jsonl"))
    monkeypatch.setenv("LLM_GENERATION_CACHE_ENABLED", "0")
    return output_dir


def test_chat_helper_uses_gateway_cache_for_non_generation_tasks(
    monkeypatch: pytest.MonkeyPatch,
    gateway_env: Path,
) -> None:
    del gateway_env
    gateway_mod = _load_gateway()
    response = _FakeResponse()
    adapter, completions = _make_adapter(response)
    log_calls: list[dict] = []
    gateway_calls: list[dict] = []

    def _capture_gated_call(**kwargs):
        gateway_calls.append(kwargs)
        return gateway_mod.gated_call(**kwargs)

    monkeypatch.setattr(ai_mod, "gated_call", _capture_gated_call)
    monkeypatch.setattr(ai_mod, "log_llm_call", lambda **kwargs: log_calls.append(kwargs))

    first = adapter._chat(
        "提取这段内容",
        task="extraction",
        response_format={"type": "json_object"},
    )
    second = adapter._chat(
        "提取这段内容",
        task="extraction",
        response_format={"type": "json_object"},
    )

    assert first is response
    assert second.choices[0].message.content == "{}"
    assert len(completions.calls) == 1
    assert len(gateway_calls) == 2
    assert gateway_calls[0]["kind"] == "llm"
    assert gateway_calls[0]["cache_key_parts"] == {
        "model": "qwen-max",
        "prompt_hash": _prompt_hash("提取这段内容"),
        "sampling_params_hash": _sampling_hash(
            {
                "temperature": 0.1,
                "top_p": 0.5,
                "max_tokens": 4096,
                "top_k": 20,
                "response_format": {"type": "json_object"},
            }
        ),
        "task": "extraction",
    }
    assert len(log_calls) == 2
    assert log_calls[0]["cache_status"] == "miss"
    assert log_calls[0]["decision"] == "invoke"
    assert log_calls[1]["cache_status"] == "hit"
    assert log_calls[1]["decision"] == "cache_hit"


def test_chat_helper_generation_keeps_gateway_invoke_telemetry_by_default(
    monkeypatch: pytest.MonkeyPatch,
    gateway_env: Path,
) -> None:
    del gateway_env
    gateway_mod = _load_gateway()
    response = _FakeResponse(content="生成结果")
    adapter, completions = _make_adapter(response)
    log_calls: list[dict] = []
    gateway_calls: list[dict] = []

    def _capture_gated_call(**kwargs):
        gateway_calls.append(kwargs)
        return gateway_mod.gated_call(**kwargs)

    monkeypatch.setattr(ai_mod, "gated_call", _capture_gated_call)
    monkeypatch.setattr(ai_mod, "log_llm_call", lambda **kwargs: log_calls.append(kwargs))

    first = adapter._chat("生成回答", task="generation")
    second = adapter._chat("生成回答", task="generation")

    assert first is response
    assert second is response
    assert len(completions.calls) == 2
    assert len(gateway_calls) == 2
    assert gateway_calls[0]["cache_key_parts"] == {
        "model": "qwen-max",
        "prompt_hash": _prompt_hash("生成回答"),
        "sampling_params_hash": _sampling_hash(
            {
                "temperature": 0.7,
                "top_p": 0.9,
                "max_tokens": 2048,
                "top_k": 50,
            }
        ),
        "task": "generation",
    }
    assert [call["cache_status"] for call in log_calls] == ["miss", "miss"]
    assert [call["decision"] for call in log_calls] == ["invoke", "invoke"]


def test_chat_helper_uses_task_defaults_and_logs_usage(monkeypatch) -> None:
    response = _FakeResponse()
    adapter, completions = _make_adapter(response)
    log_calls: list[dict] = []

    monkeypatch.setattr(ai_mod, "log_llm_call", lambda **kwargs: log_calls.append(kwargs))

    returned = adapter._chat(
        "提取这段内容",
        task="extraction",
        response_format={"type": "json_object"},
    )

    assert returned is response
    assert len(completions.calls) == 1
    kwargs = completions.calls[0]
    assert kwargs["model"] == "qwen-max"
    assert kwargs["messages"] == [{"role": "user", "content": "提取这段内容"}]
    assert kwargs["temperature"] == 0.1
    assert kwargs["top_p"] == 0.5
    assert kwargs["max_tokens"] == 4096
    assert kwargs["extra_body"] == {"top_k": 20}
    assert kwargs["response_format"] == {"type": "json_object"}

    assert len(log_calls) == 1
    assert log_calls[0]["model"] == "qwen-max"
    assert log_calls[0]["task"] == "extraction"
    assert log_calls[0]["prompt_tokens"] == 11
    assert log_calls[0]["completion_tokens"] == 7
    assert log_calls[0]["status"] == "ok"
    assert log_calls[0]["cache_status"] == "miss"
    assert log_calls[0]["decision"] == "invoke"
    assert log_calls[0]["latency_ms"] >= 0


def test_chat_helper_logs_error_rows_as_generation_miss_invoke(monkeypatch) -> None:
    adapter = object.__new__(AIAdapter)
    adapter.client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=_FailingCompletions()))
    adapter.model = "qwen-max"
    adapter.enabled = True
    log_calls: list[dict] = []

    monkeypatch.setattr(ai_mod, "log_llm_call", lambda **kwargs: log_calls.append(kwargs))

    with pytest.raises(RuntimeError, match="vendor failed"):
        adapter._chat("提取失败", task="extraction")

    assert len(log_calls) == 1
    assert log_calls[0]["status"] == "error"
    assert log_calls[0]["prompt_tokens"] == 0
    assert log_calls[0]["completion_tokens"] == 0
    assert log_calls[0]["cache_status"] == "miss"
    assert log_calls[0]["decision"] == "invoke"


def test_chat_helper_swallows_telemetry_failures(monkeypatch) -> None:
    response = _FakeResponse()
    adapter, _ = _make_adapter(response)

    def _boom(**kwargs):
        raise RuntimeError("telemetry failed")

    monkeypatch.setattr(ai_mod, "log_llm_call", _boom)

    returned = adapter._chat("仍然返回响应", task="rewrite")

    assert returned is response


def test_verify_multimodal_support_keeps_short_completion_contract() -> None:
    adapter = object.__new__(AIAdapter)
    adapter.enabled = True
    captured: dict[str, object] = {}

    def _fake_chat(prompt: str, *, task: str, overrides=None, response_format=None):
        captured["prompt"] = prompt
        captured["task"] = task
        captured["overrides"] = overrides
        captured["response_format"] = response_format
        return _FakeResponse(content="0.9")

    adapter._chat = _fake_chat

    score = adapter.verify_multimodal_support("文本结论", "图表标题")

    assert score == 0.9
    assert captured["task"] == "extraction"
    assert captured["overrides"] == {"temperature": 0.1, "max_tokens": 10}
    assert captured["response_format"] is None


def test_classify_claim_boundary_keeps_temperature_override_and_json_mode() -> None:
    adapter = object.__new__(AIAdapter)
    adapter.enabled = True
    captured: dict[str, object] = {}

    def _fake_chat(prompt: str, *, task: str, overrides=None, response_format=None):
        captured["prompt"] = prompt
        captured["task"] = task
        captured["overrides"] = overrides
        captured["response_format"] = response_format
        return _FakeResponse(
            content='{"boundary_type":"explanation","confidence":0.8,"justification":"依据原文","evidence_indicators":["由于"]}'
        )

    adapter._chat = _fake_chat

    result = adapter.classify_claim_boundary("主张", "源文本")

    assert result["claim"] == "主张"
    assert result["boundary_type"] == "explanation"
    assert captured["task"] == "extraction"
    assert captured["overrides"] == {"temperature": 0.2}
    assert captured["response_format"] == {"type": "json_object"}
