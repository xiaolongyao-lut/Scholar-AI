"""Tests for model_dispatcher (Slice C / DEC-004 / Hard Constraints #2 #3 #12)."""

from __future__ import annotations

import asyncio
import os
import time

import pytest

from model_dispatcher import (
    DispatchBatchResult,
    DispatchCandidate,
    DispatchMode,
    DispatcherAllFailedError,
    DispatcherEmptyError,
    DispatcherRaceDisabledError,
    ainvoke_broadcast,
    ainvoke_failover,
    ainvoke_fanout,
    ainvoke_race,
    arun_parallel_round,
    invoke_failover,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _cand(
    cid: str,
    *,
    priority: int = 100,
    provider: str = "openai",
    model: str = "gpt-4o",
    agent_id: str | None = None,
    role: str | None = None,
) -> DispatchCandidate:
    return DispatchCandidate(
        candidate_id=cid,
        provider=provider,
        model=model,
        priority=priority,
        agent_id=agent_id,
        role=role,
    )


# ---------------------------------------------------------------------------
# Failover (sync)
# ---------------------------------------------------------------------------


def test_failover_first_success_short_circuits() -> None:
    calls: list[str] = []

    def invoke(c: DispatchCandidate) -> str:
        calls.append(c.candidate_id)
        return f"ok:{c.candidate_id}"

    batch = invoke_failover(
        [_cand("a", priority=1), _cand("b", priority=2), _cand("c", priority=3)],
        invoke,
    )
    assert batch.first_success.candidate_id == "a"
    assert batch.total_succeeded == 1
    assert batch.total_attempted == 1
    assert calls == ["a"]


def test_failover_priority_order_is_respected() -> None:
    calls: list[str] = []

    def invoke(c: DispatchCandidate) -> str:
        calls.append(c.candidate_id)
        if c.candidate_id != "a":
            return "ok"
        raise RuntimeError("a fails")

    invoke_failover(
        [_cand("c", priority=3), _cand("a", priority=1), _cand("b", priority=2)],
        invoke,
    )
    assert calls == ["a", "b"]  # sorted by priority ascending; b succeeds


def test_failover_all_fail_raises_with_batch() -> None:
    def invoke(c: DispatchCandidate) -> str:
        raise RuntimeError(f"boom:{c.candidate_id}")

    with pytest.raises(DispatcherAllFailedError) as excinfo:
        invoke_failover([_cand("a"), _cand("b")], invoke)
    batch = excinfo.value.batch
    assert batch.total_succeeded == 0
    assert batch.total_attempted == 2
    assert all(r.error is not None for r in batch.results)


def test_failover_no_raise_returns_failed_batch() -> None:
    def invoke(c):
        raise RuntimeError("nope")

    batch = invoke_failover([_cand("a")], invoke, raise_on_all_fail=False)
    assert batch.total_succeeded == 0
    assert batch.results[0].error.error_class == "RuntimeError"


def test_failover_empty_candidates_raises() -> None:
    with pytest.raises(DispatcherEmptyError):
        invoke_failover([], lambda c: "ok")


def test_failover_error_summary_truncates_long_messages() -> None:
    def invoke(c):
        raise RuntimeError("x" * 1000)

    batch = invoke_failover([_cand("a")], invoke, raise_on_all_fail=False)
    msg = batch.results[0].error.message
    assert len(msg) <= 256


# ---------------------------------------------------------------------------
# Async failover
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_failover_first_success() -> None:
    calls: list[str] = []

    async def invoke(c):
        calls.append(c.candidate_id)
        if c.candidate_id == "a":
            raise RuntimeError("a fails")
        return f"ok:{c.candidate_id}"

    batch = await ainvoke_failover(
        [_cand("a", priority=1), _cand("b", priority=2)], invoke
    )
    assert batch.first_success.candidate_id == "b"
    assert calls == ["a", "b"]


# ---------------------------------------------------------------------------
# Race
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_race_returns_fastest_winner_and_cancels_others() -> None:
    delays = {"slow": 0.5, "mid": 0.2, "fast": 0.05}
    started: list[str] = []
    cancelled: list[str] = []

    async def invoke(c):
        started.append(c.candidate_id)
        try:
            await asyncio.sleep(delays[c.candidate_id])
        except asyncio.CancelledError:
            cancelled.append(c.candidate_id)
            raise
        return f"ok:{c.candidate_id}"

    batch = await ainvoke_race(
        [_cand("slow"), _cand("mid"), _cand("fast")],
        invoke,
        timeout_seconds=2.0,
        max_concurrency=3,
    )
    assert batch.first_success.candidate_id == "fast"
    assert batch.total_succeeded == 1
    assert batch.total_skipped == 0
    # Slower candidates were cancelled (best-effort; CPython >= 3.10 reliable)
    assert "slow" in cancelled or "mid" in cancelled


@pytest.mark.asyncio
async def test_race_caps_to_max_concurrency() -> None:
    cands = [_cand(f"c{i}", priority=i) for i in range(10)]
    started: list[str] = []

    async def invoke(c):
        started.append(c.candidate_id)
        await asyncio.sleep(0.01)
        return c.candidate_id

    batch = await ainvoke_race(cands, invoke, timeout_seconds=2.0, max_concurrency=3)
    assert batch.total_attempted == 3
    assert batch.total_skipped == 7
    skipped = [r for r in batch.results if r.skipped]
    assert len(skipped) == 7
    assert all(r.skip_reason == "skipped_by_priority_filter" for r in skipped)
    # Only top-3 by priority were started
    assert set(started).issubset({"c0", "c1", "c2"})


@pytest.mark.asyncio
async def test_race_disabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_DISPATCHER_ALLOW_RACE", "0")
    with pytest.raises(DispatcherRaceDisabledError):
        await ainvoke_race([_cand("a")], lambda c: c, timeout_seconds=1.0)


@pytest.mark.asyncio
async def test_race_all_fail_returns_zero_success_batch() -> None:
    async def invoke(c):
        raise RuntimeError("nope")

    batch = await ainvoke_race(
        [_cand("a"), _cand("b")], invoke, timeout_seconds=1.0, max_concurrency=2
    )
    assert batch.total_succeeded == 0
    assert batch.total_attempted == 2
    assert batch.first_success is None


# ---------------------------------------------------------------------------
# Fanout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fanout_partial_failures_returns_all() -> None:
    async def invoke(c):
        if c.candidate_id == "bad":
            raise RuntimeError("bad failed")
        return c.candidate_id.upper()

    batch = await ainvoke_fanout(
        [_cand("a"), _cand("bad"), _cand("c")], invoke,
        timeout_seconds=1.0, max_concurrency=3,
    )
    assert batch.total_attempted == 3
    assert batch.total_succeeded == 2
    assert len(batch.errors) == 1
    assert batch.errors[0].candidate_id == "bad"
    success_ids = {r.candidate_id for r in batch.successes}
    assert success_ids == {"a", "c"}


@pytest.mark.asyncio
async def test_fanout_caps_to_max_concurrency_and_marks_skipped() -> None:
    cands = [_cand(f"c{i}", priority=i) for i in range(6)]

    async def invoke(c):
        return c.candidate_id

    batch = await ainvoke_fanout(cands, invoke, timeout_seconds=1.0, max_concurrency=2)
    assert batch.total_attempted == 2
    assert batch.total_skipped == 4
    skipped_ids = {r.candidate_id for r in batch.results if r.skipped}
    assert skipped_ids == {"c2", "c3", "c4", "c5"}


@pytest.mark.asyncio
async def test_fanout_timeout_per_call() -> None:
    async def invoke(c):
        if c.candidate_id == "slow":
            await asyncio.sleep(2.0)
            return "should_not_reach"
        return "fast_ok"

    batch = await ainvoke_fanout(
        [_cand("slow"), _cand("fast")], invoke,
        timeout_seconds=0.1, max_concurrency=2,
    )
    slow = next(r for r in batch.results if r.candidate_id == "slow")
    assert not slow.success
    assert slow.error.error_class in {"TimeoutError", "CancelledError"}
    assert slow.error.retry_recommended is True


# ---------------------------------------------------------------------------
# Broadcast (no priority cap)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcast_runs_all_no_skipped() -> None:
    cands = [_cand(f"c{i}", priority=i) for i in range(5)]

    async def invoke(c):
        return c.candidate_id

    batch = await ainvoke_broadcast(cands, invoke, timeout_seconds=1.0)
    assert batch.total_attempted == 5
    assert batch.total_succeeded == 5
    assert batch.total_skipped == 0


# ---------------------------------------------------------------------------
# Parallel round (agent slots)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_round_results_carry_agent_id_and_role() -> None:
    slots = [
        _cand("c1", agent_id="a1", role="proposer"),
        _cand("c2", agent_id="a2", role="critic"),
        _cand("c3", agent_id="a3", role="synthesizer"),
    ]

    async def invoke(c):
        return f"out:{c.role}"

    batch = await arun_parallel_round(slots, invoke, timeout_seconds=1.0, max_concurrency=3)
    assert batch.total_attempted == 3
    assert batch.total_succeeded == 3
    by_role = {r.role: r for r in batch.results}
    assert by_role["proposer"].agent_id == "a1"
    assert by_role["critic"].agent_id == "a2"
    assert by_role["synthesizer"].agent_id == "a3"
    for r in batch.results:
        assert r.latency_ms >= 0
        assert r.success is True


@pytest.mark.asyncio
async def test_parallel_round_rejects_slot_without_agent_id() -> None:
    slots = [_cand("c1")]  # no agent_id

    async def invoke(c):
        return c.candidate_id

    with pytest.raises(ValueError, match="agent_id"):
        await arun_parallel_round(slots, invoke, timeout_seconds=1.0)


@pytest.mark.asyncio
async def test_parallel_round_one_agent_fails_others_proceed() -> None:
    slots = [
        _cand("c1", agent_id="a1", role="proposer"),
        _cand("c2", agent_id="a2", role="critic"),
    ]

    async def invoke(c):
        if c.role == "critic":
            raise RuntimeError("critic broke")
        return "ok"

    batch = await arun_parallel_round(slots, invoke, timeout_seconds=1.0)
    assert batch.total_succeeded == 1
    failed = next(r for r in batch.results if not r.success)
    assert failed.role == "critic"
    assert failed.error.error_class == "RuntimeError"


# ---------------------------------------------------------------------------
# Metadata redaction
# ---------------------------------------------------------------------------


def test_dispatch_candidate_does_not_carry_secrets() -> None:
    """DispatchCandidate must be safe to log; secrets live in the closure."""
    c = _cand("a")
    d = c.__dict__
    assert "api_key" not in d
    assert "secret" not in d


def test_dispatch_result_as_dict_does_not_leak_output_to_log_view() -> None:
    """as_dict drops the raw output (which may contain provider tokens) and
    keeps only structured metadata."""
    def invoke(c):
        return {"choices": [{"message": {"content": "hello"}}]}

    batch = invoke_failover([_cand("a")], invoke)
    d = batch.as_dict()
    serialized = str(d)
    assert "choices" not in serialized
    assert "hello" not in serialized
    # But output IS available on the in-memory object for the caller
    assert batch.first_success.output["choices"][0]["message"]["content"] == "hello"


def test_error_summary_truncates_to_256_chars() -> None:
    long = "secret_in_url=" + "x" * 500

    def invoke(c):
        raise ValueError(long)

    batch = invoke_failover([_cand("a")], invoke, raise_on_all_fail=False)
    assert len(batch.results[0].error.message) <= 256


# ---------------------------------------------------------------------------
# Env knobs
# ---------------------------------------------------------------------------


def test_max_concurrency_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from model_dispatcher import max_concurrency_default
    monkeypatch.setenv("MODEL_DISPATCHER_MAX_CONCURRENCY", "7")
    assert max_concurrency_default() == 7


def test_default_timeout_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from model_dispatcher import default_timeout_seconds
    monkeypatch.setenv("MODEL_DISPATCHER_DEFAULT_TIMEOUT_SECONDS", "12.5")
    assert default_timeout_seconds() == 12.5


def test_invalid_env_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from model_dispatcher import max_concurrency_default
    monkeypatch.setenv("MODEL_DISPATCHER_MAX_CONCURRENCY", "not_a_number")
    assert max_concurrency_default() == 4


# ---------------------------------------------------------------------------
# BatchResult shape
# ---------------------------------------------------------------------------


def test_batch_result_first_success_picks_first_in_order() -> None:
    def invoke(c):
        if c.candidate_id == "a":
            raise RuntimeError("a")
        return "ok"

    batch = invoke_failover(
        [_cand("a", priority=1), _cand("b", priority=2)], invoke
    )
    assert batch.first_success.candidate_id == "b"


def test_batch_result_successes_and_errors_partitions() -> None:
    async def invoke(c):
        if c.candidate_id in {"a", "c"}:
            return "ok"
        raise RuntimeError("nope")

    batch = asyncio.run(
        ainvoke_fanout(
            [_cand("a"), _cand("b"), _cand("c")],
            invoke,
            timeout_seconds=1.0,
            max_concurrency=3,
        )
    )
    assert {r.candidate_id for r in batch.successes} == {"a", "c"}
    assert {r.candidate_id for r in batch.errors} == {"b"}
