from __future__ import annotations

import importlib
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest


def _load_gateway():
    if "model_call_gateway" in sys.modules:
        return importlib.reload(sys.modules["model_call_gateway"])
    return importlib.import_module("model_call_gateway")


@pytest.fixture
def gateway_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MODEL_CALL_GATEWAY_CACHE_DIR", str(output_dir / "gateway_cache"))
    monkeypatch.setenv("MODEL_CALL_GATEWAY_METRICS_PATH", str(output_dir / "gateway_metrics.jsonl"))
    monkeypatch.setenv("LLM_GENERATION_CACHE_ENABLED", "0")
    return output_dir


def test_exact_cache_hit_avoids_second_invoke(gateway_env: Path) -> None:
    mg = _load_gateway()
    calls = 0

    def invoke():
        nonlocal calls
        calls += 1
        return {"value": "cached"}

    first = mg.gated_call(
        kind="embedding",
        cache_key_parts={
            "model": "embed-v1",
            "normalized_text": "alpha",
            "chunking_version": "v1",
        },
        payload="alpha",
        invoke=invoke,
    )
    second = mg.gated_call(
        kind="embedding",
        cache_key_parts={
            "model": "embed-v1",
            "normalized_text": "alpha",
            "chunking_version": "v1",
        },
        payload="alpha",
        invoke=invoke,
    )

    assert first == {"value": "cached"}
    assert second == {"value": "cached"}
    assert calls == 1


def test_cache_miss_writes_disk_entry_for_embedding(gateway_env: Path) -> None:
    mg = _load_gateway()

    result = mg.gated_call(
        kind="embedding",
        cache_key_parts={
            "model": "embed-v1",
            "normalized_text": "beta",
            "chunking_version": "v1",
        },
        payload="beta",
        invoke=lambda: {"value": "written"},
    )

    cache_files = list((gateway_env / "gateway_cache" / "embedding").rglob("*.json"))
    assert result == {"value": "written"}
    assert len(cache_files) == 1


def test_skip_predicate_true_skips_invoke(gateway_env: Path) -> None:
    mg = _load_gateway()
    called = False

    def invoke():
        nonlocal called
        called = True
        return {"value": "should not happen"}

    result = mg.gated_call(
        kind="rerank",
        cache_key_parts={
            "model": "rerank-v1",
            "query_normalized": "question",
            "candidate_chunk_ids": ["c1", "c2"],
            "corpus_version": "corpus-a",
        },
        payload={"query": "question"},
        invoke=invoke,
        skip_predicate=lambda: True,
    )

    assert result is None
    assert called is False


def test_retry_after_header_delays_and_then_succeeds(gateway_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mg = _load_gateway()
    delays: list[float] = []
    attempts = 0

    monkeypatch.setattr(mg.time, "sleep", lambda seconds: delays.append(seconds))
    monkeypatch.setattr(mg.random, "uniform", lambda _start, _end: 0.0)

    def invoke():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            request = httpx.Request("POST", "https://example.test/rerank")
            response = httpx.Response(429, headers={"Retry-After": "2"}, request=request)
            raise httpx.HTTPStatusError("rate limited", request=request, response=response)
        return {"value": "ok"}

    result = mg.gated_call(
        kind="rerank",
        cache_key_parts={
            "model": "rerank-v1",
            "query_normalized": "retry",
            "candidate_chunk_ids": ["c1", "c2"],
            "corpus_version": "corpus-a",
        },
        payload={"query": "retry"},
        invoke=invoke,
    )

    assert result == {"value": "ok"}
    assert attempts == 2
    assert delays == [2.0]


def test_retryable_error_raises_after_retry_budget_exhausted(
    gateway_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mg = _load_gateway()
    attempts = 0

    monkeypatch.setattr(mg.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(mg.random, "uniform", lambda _start, _end: 0.0)

    def invoke():
        nonlocal attempts
        attempts += 1
        request = httpx.Request("POST", "https://example.test/embed")
        response = httpx.Response(503, request=request)
        raise httpx.HTTPStatusError("temporary failure", request=request, response=response)

    with pytest.raises(httpx.HTTPStatusError, match="temporary failure"):
        mg.gated_call(
            kind="embedding",
            cache_key_parts={
                "model": "embed-v1",
                "normalized_text": "retry-exhausted",
                "chunking_version": "v1",
            },
            payload="retry-exhausted",
            invoke=invoke,
        )

    assert attempts == 3


def test_schema_validation_failure_does_not_write_cache(gateway_env: Path) -> None:
    mg = _load_gateway()
    calls = 0

    def invoke():
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"bad": True}
        return {"ok": True}

    validator = lambda value: isinstance(value, dict) and value.get("ok") is True

    with pytest.raises(ValueError, match="schema validation"):
        mg.gated_call(
            kind="embedding",
            cache_key_parts={
                "model": "embed-v1",
                "normalized_text": "schema-check",
                "chunking_version": "v1",
            },
            payload="schema-check",
            invoke=invoke,
            validate_result=validator,
        )

    result = mg.gated_call(
        kind="embedding",
        cache_key_parts={
            "model": "embed-v1",
            "normalized_text": "schema-check",
            "chunking_version": "v1",
        },
        payload="schema-check",
        invoke=invoke,
        validate_result=validator,
    )

    assert result == {"ok": True}
    assert calls == 2


def test_embedding_kind_semaphore_caps_concurrency_at_four(gateway_env: Path) -> None:
    mg = _load_gateway()
    active = 0
    max_active = 0
    lock = threading.Lock()
    errors: list[BaseException] = []

    def make_invoke(index: int):
        def invoke():
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return {"index": index}

        return invoke

    def worker(index: int) -> None:
        try:
            mg.gated_call(
                kind="embedding",
                cache_key_parts={
                    "model": "embed-v1",
                    "normalized_text": f"concurrency-{index}",
                    "chunking_version": "v1",
                },
                payload=f"concurrency-{index}",
                invoke=make_invoke(index),
            )
        except BaseException as exc:  # pragma: no cover - failure path assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert errors == []
    assert max_active == 4


def test_rerank_kind_semaphore_respects_env_override(
    gateway_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SILICONFLOW_RERANK_CONCURRENCY", "5")
    mg = _load_gateway()
    active = 0
    max_active = 0
    lock = threading.Lock()
    errors: list[Exception] = []

    def make_invoke(index: int):
        def invoke():
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return {"index": index}

        return invoke

    def worker(index: int) -> None:
        try:
            mg.gated_call(
                kind="rerank",
                cache_key_parts={
                    "model": "rerank-v1",
                    "query_normalized": f"override-{index}",
                    "candidate_chunk_ids": [f"c{index}", f"c{index + 100}"],
                    "corpus_version": "corpus-a",
                },
                payload={"query": f"override-{index}"},
                invoke=make_invoke(index),
            )
        except Exception as exc:  # pragma: no cover - failure path assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert errors == []
    assert max_active == 5


def test_corpus_version_change_invalidates_old_cache(gateway_env: Path) -> None:
    mg = _load_gateway()
    calls = 0

    def invoke():
        nonlocal calls
        calls += 1
        return {"value": calls}

    first = mg.gated_call(
        kind="rerank",
        cache_key_parts={
            "model": "rerank-v1",
            "query_normalized": "corpus-version",
            "candidate_chunk_ids": ["c1", "c2"],
            "corpus_version": "corpus-a",
        },
        payload={"query": "corpus-version"},
        invoke=invoke,
    )
    second = mg.gated_call(
        kind="rerank",
        cache_key_parts={
            "model": "rerank-v1",
            "query_normalized": "corpus-version",
            "candidate_chunk_ids": ["c1", "c2"],
            "corpus_version": "corpus-b",
        },
        payload={"query": "corpus-version"},
        invoke=invoke,
    )

    assert first == {"value": 1}
    assert second == {"value": 2}
    assert calls == 2


def test_llm_generation_task_bypasses_cache_by_default(gateway_env: Path) -> None:
    mg = _load_gateway()
    calls = 0

    def invoke():
        nonlocal calls
        calls += 1
        return {"value": f"answer-{calls}"}

    first = mg.gated_call(
        kind="llm",
        cache_key_parts={
            "model": "qwen-max",
            "prompt_hash": "p1",
            "sampling_params_hash": "s1",
            "task": "generation",
        },
        payload={"prompt": "hello"},
        invoke=invoke,
    )
    second = mg.gated_call(
        kind="llm",
        cache_key_parts={
            "model": "qwen-max",
            "prompt_hash": "p1",
            "sampling_params_hash": "s1",
            "task": "generation",
        },
        payload={"prompt": "hello"},
        invoke=invoke,
    )

    assert first == {"value": "answer-1"}
    assert second == {"value": "answer-2"}
    assert calls == 2


def test_metrics_record_includes_stage_for_invoke(gateway_env: Path) -> None:
    mg = _load_gateway()
    metrics_path = gateway_env / "gateway_metrics.jsonl"

    result = mg.gated_call(
        kind="embedding",
        cache_key_parts={
            "model": "embed-v1",
            "normalized_text": "stage-invoke",
            "chunking_version": "v1",
        },
        payload="stage-invoke",
        invoke=lambda: {"value": "ok"},
        stage="query",
    )

    assert result == {"value": "ok"}
    records = [
        line for line in metrics_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert records
    last = __import__("json").loads(records[-1])
    assert last["stage"] == "query"


def test_metrics_record_includes_stage_for_cache_hit(gateway_env: Path) -> None:
    mg = _load_gateway()
    metrics_path = gateway_env / "gateway_metrics.jsonl"

    _ = mg.gated_call(
        kind="embedding",
        cache_key_parts={
            "model": "embed-v1",
            "normalized_text": "stage-hit",
            "chunking_version": "v1",
        },
        payload="stage-hit",
        invoke=lambda: {"value": "warm"},
        stage="build",
    )
    _ = mg.gated_call(
        kind="embedding",
        cache_key_parts={
            "model": "embed-v1",
            "normalized_text": "stage-hit",
            "chunking_version": "v1",
        },
        payload="stage-hit",
        invoke=lambda: {"value": "should-not-run"},
        stage="build",
    )

    records = [
        __import__("json").loads(line)
        for line in metrics_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    hit_records = [r for r in records if r.get("decision") == "cache_hit"]
    assert hit_records
    assert hit_records[-1]["stage"] == "build"
