"""Model Dispatcher (Slice C / DEC-004 / Hard Constraints #2 #3 #12 #13).

Reusable invocation semantics on top of caller-provided ``invoke(candidate)``
functions. The dispatcher does NOT own credentials or call providers itself —
it only orchestrates which candidate(s) run and how their results merge.

Modes (plan v2 §13.1):
    failover       sequential; first success wins
    race           top-N concurrent; first success wins, others cancelled
    fanout         top-N concurrent; gather successes + structured errors
    broadcast      ALL candidates concurrent (no priority cap)
    parallel_round per-agent slot; gather all results with agent_id/role

Hard constraints honored:
    #2  This module is for NEW callers (Slice D). The four existing A2 pool
        callsites are NOT migrated here until Slice C+1 parity work.
    #3  Race / fanout cap to ``max_concurrency`` after priority sort. Filtered
        candidates are returned as ``skipped=True``,
        ``skip_reason='skipped_by_priority_filter'``.
    #12 ``max_concurrency`` is per-call only. Cross-call agent caps are owned
        by the discussion orchestrator (``DISCUSSION_AGENT_MAX_CONCURRENCY``).
    #13 No capability matching. Caller picks candidate set.

Env knobs:
    MODEL_DISPATCHER_MAX_CONCURRENCY        default 4
    MODEL_DISPATCHER_DEFAULT_TIMEOUT_SECONDS default 60.0
    MODEL_DISPATCHER_ALLOW_RACE             default true
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Iterable


logger = logging.getLogger("ModelDispatcher")


# ---------------------------------------------------------------------------
# Env knobs
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        v = int(raw)
        return v if v > 0 else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        v = float(raw)
        return v if v > 0 else default
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def max_concurrency_default() -> int:
    return _env_int("MODEL_DISPATCHER_MAX_CONCURRENCY", 4)


def default_timeout_seconds() -> float:
    return _env_float("MODEL_DISPATCHER_DEFAULT_TIMEOUT_SECONDS", 60.0)


def race_allowed() -> bool:
    return _env_bool("MODEL_DISPATCHER_ALLOW_RACE", True)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DispatcherError(RuntimeError):
    pass


class DispatcherAllFailedError(DispatcherError):
    """All eligible candidates raised. Carries the batch for inspection."""

    def __init__(self, message: str, batch: "DispatchBatchResult") -> None:
        super().__init__(message)
        self.batch = batch


class DispatcherEmptyError(DispatcherError):
    pass


class DispatcherRaceDisabledError(DispatcherError):
    pass


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class DispatchMode(str, Enum):
    FAILOVER = "failover"
    RACE = "race"
    FANOUT = "fanout"
    BROADCAST = "broadcast"
    PARALLEL_ROUND = "parallel_round"


@dataclass(frozen=True)
class DispatchCandidate:
    """Identity + routing info for one candidate.

    Secrets are NOT stored as top-level fields here — the caller closes over
    them inside its ``invoke(candidate)`` function. Top-level fields are safe
    to log. ``metadata`` follows a naming convention: keys starting with an
    underscore (e.g. ``_resolved_api_key``, ``_context_items``) are private
    transport-only payloads that **must NOT** be logged or serialized by
    consumers — they may carry credentials, evidence text, or other sensitive
    content. Use the helper :func:`dump_metadata_safe_to_log` (or apply the
    ``_``-prefix filter yourself) before any log/trace dump.
    """

    candidate_id: str
    provider: str
    model: str
    base_url: str = ""
    credential_id: str | None = None
    priority: int = 100
    metadata: dict[str, Any] = field(default_factory=dict)
    agent_id: str | None = None
    role: str | None = None


def dump_metadata_safe_to_log(metadata: dict[str, Any]) -> dict[str, Any]:
    """Strip private (``_``-prefixed) keys from ``DispatchCandidate.metadata``
    so the result is safe to log / serialize per the docstring contract.

    Private keys carry transport-only payloads such as resolved API keys
    (``_resolved_api_key``) and inlined evidence text (``_context_items``).
    Logging them would leak secrets and large opaque blobs into operator
    surfaces. Use this helper at every dump site.
    """
    return {k: v for k, v in metadata.items() if not k.startswith("_")}


@dataclass(frozen=True)
class DispatchErrorSummary:
    error_class: str
    message: str
    retry_recommended: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_class": self.error_class,
            "message": self.message,
            "retry_recommended": self.retry_recommended,
        }


@dataclass(frozen=True)
class DispatchResult:
    candidate_id: str
    provider: str
    model: str
    success: bool
    latency_ms: float = 0.0
    output: Any = None
    error: DispatchErrorSummary | None = None
    skipped: bool = False
    skip_reason: str | None = None
    agent_id: str | None = None
    role: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "provider": self.provider,
            "model": self.model,
            "success": self.success,
            "latency_ms": round(self.latency_ms, 3),
            "error": self.error.as_dict() if self.error else None,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "agent_id": self.agent_id,
            "role": self.role,
        }


@dataclass(frozen=True)
class DispatchBatchResult:
    mode: str
    results: tuple[DispatchResult, ...]
    elapsed_ms: float
    total_attempted: int
    total_succeeded: int
    total_skipped: int

    @property
    def first_success(self) -> DispatchResult | None:
        for r in self.results:
            if r.success:
                return r
        return None

    @property
    def successes(self) -> tuple[DispatchResult, ...]:
        return tuple(r for r in self.results if r.success)

    @property
    def errors(self) -> tuple[DispatchResult, ...]:
        return tuple(r for r in self.results if not r.success and not r.skipped)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "total_attempted": self.total_attempted,
            "total_succeeded": self.total_succeeded,
            "total_skipped": self.total_skipped,
            "results": [r.as_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _summarize_error(exc: BaseException) -> DispatchErrorSummary:
    """Build a mask-safe error summary. Caller's invoke() may include URLs or
    keys in exception messages; we only keep type and a length-bounded class
    label. Message is kept but truncated to limit blast radius.
    """
    msg = str(exc)
    if len(msg) > 256:
        msg = msg[:253] + "..."
    cls = type(exc).__name__
    retry = isinstance(exc, (TimeoutError, asyncio.TimeoutError))
    return DispatchErrorSummary(error_class=cls, message=msg, retry_recommended=retry)


def _sort_by_priority(candidates: Iterable[DispatchCandidate]) -> list[DispatchCandidate]:
    return sorted(candidates, key=lambda c: (c.priority, c.candidate_id))


def _select_top_n(
    candidates: list[DispatchCandidate],
    *,
    cap: int | None,
) -> tuple[list[DispatchCandidate], list[DispatchCandidate]]:
    """Return (selected, skipped_by_priority_filter)."""
    effective_cap = cap if cap is not None else max_concurrency_default()
    if effective_cap <= 0:
        return [], list(candidates)
    return list(candidates[:effective_cap]), list(candidates[effective_cap:])


def _make_skipped_result(c: DispatchCandidate, reason: str) -> DispatchResult:
    return DispatchResult(
        candidate_id=c.candidate_id,
        provider=c.provider,
        model=c.model,
        success=False,
        latency_ms=0.0,
        skipped=True,
        skip_reason=reason,
        agent_id=c.agent_id,
        role=c.role,
    )


def _make_success_result(
    c: DispatchCandidate, output: Any, latency_ms: float
) -> DispatchResult:
    return DispatchResult(
        candidate_id=c.candidate_id,
        provider=c.provider,
        model=c.model,
        success=True,
        latency_ms=latency_ms,
        output=output,
        agent_id=c.agent_id,
        role=c.role,
    )


def _make_error_result(
    c: DispatchCandidate, exc: BaseException, latency_ms: float
) -> DispatchResult:
    return DispatchResult(
        candidate_id=c.candidate_id,
        provider=c.provider,
        model=c.model,
        success=False,
        latency_ms=latency_ms,
        error=_summarize_error(exc),
        agent_id=c.agent_id,
        role=c.role,
    )


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


# ---------------------------------------------------------------------------
# Sync failover
# ---------------------------------------------------------------------------


def invoke_failover(
    candidates: Iterable[DispatchCandidate],
    invoke: Callable[[DispatchCandidate], Any],
    *,
    timeout_seconds: float | None = None,
    raise_on_all_fail: bool = True,
) -> DispatchBatchResult:
    """Sequential invocation; first success wins.

    Cooldown semantics are owned by the caller's ``invoke``; this dispatcher
    only orders attempts and shapes the batch result.
    """
    sorted_cands = _sort_by_priority(candidates)
    if not sorted_cands:
        raise DispatcherEmptyError("no candidates supplied")

    timeout = timeout_seconds if timeout_seconds is not None else default_timeout_seconds()
    started = _now_ms()
    results: list[DispatchResult] = []

    for c in sorted_cands:
        attempt_start = _now_ms()
        try:
            output = _call_with_sync_timeout(invoke, c, timeout)
            latency = _now_ms() - attempt_start
            results.append(_make_success_result(c, output, latency))
            batch = DispatchBatchResult(
                mode=DispatchMode.FAILOVER.value,
                results=tuple(results),
                elapsed_ms=_now_ms() - started,
                total_attempted=len(results),
                total_succeeded=1,
                total_skipped=0,
            )
            return batch
        except Exception as exc:  # noqa: BLE001 — failover collects every candidate's failure into the batch and re-raises only after exhausting all candidates; provider exception types are unbounded so narrow except is impractical.
            latency = _now_ms() - attempt_start
            results.append(_make_error_result(c, exc, latency))
            logger.warning(
                "dispatcher.failover candidate=%s error=%s", c.candidate_id, type(exc).__name__
            )
            continue

    batch = DispatchBatchResult(
        mode=DispatchMode.FAILOVER.value,
        results=tuple(results),
        elapsed_ms=_now_ms() - started,
        total_attempted=len(results),
        total_succeeded=0,
        total_skipped=0,
    )
    if raise_on_all_fail:
        raise DispatcherAllFailedError(
            f"all {len(results)} candidates failed", batch
        )
    return batch


def _call_with_sync_timeout(
    invoke: Callable[[DispatchCandidate], Any],
    c: DispatchCandidate,
    timeout: float,
) -> Any:
    """Sync timeout via signal would be unportable on Windows; rely on the
    caller's own client-level timeout. We just enforce a wall-clock check
    after the call returns and warn if it grossly overran.
    """
    started = _now_ms()
    out = invoke(c)
    elapsed = (_now_ms() - started) / 1000.0
    if elapsed > timeout * 1.5:
        logger.warning(
            "dispatcher.failover candidate=%s exceeded soft timeout %.1fs (took %.1fs)",
            c.candidate_id, timeout, elapsed,
        )
    return out


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------


async def _await_one(
    invoke: Callable[[DispatchCandidate], Awaitable[Any]],
    c: DispatchCandidate,
    timeout: float,
) -> DispatchResult:
    started = _now_ms()
    try:
        output = await asyncio.wait_for(invoke(c), timeout=timeout)
        return _make_success_result(c, output, _now_ms() - started)
    except asyncio.CancelledError:
        # Re-raise so race can prune slower tasks cleanly.
        raise
    except Exception as exc:  # noqa: BLE001 — _await_one shapes ALL non-cancellation failures into DispatchResult.error so race/fanout/parallel_round see uniform results; provider exception classes are unbounded so a narrow except is impractical here.
        return _make_error_result(c, exc, _now_ms() - started)


async def ainvoke_failover(
    candidates: Iterable[DispatchCandidate],
    invoke: Callable[[DispatchCandidate], Awaitable[Any]],
    *,
    timeout_seconds: float | None = None,
    raise_on_all_fail: bool = True,
) -> DispatchBatchResult:
    sorted_cands = _sort_by_priority(candidates)
    if not sorted_cands:
        raise DispatcherEmptyError("no candidates supplied")
    timeout = timeout_seconds if timeout_seconds is not None else default_timeout_seconds()
    started = _now_ms()
    results: list[DispatchResult] = []
    for c in sorted_cands:
        r = await _await_one(invoke, c, timeout)
        results.append(r)
        if r.success:
            batch = DispatchBatchResult(
                mode=DispatchMode.FAILOVER.value,
                results=tuple(results),
                elapsed_ms=_now_ms() - started,
                total_attempted=len(results),
                total_succeeded=1,
                total_skipped=0,
            )
            return batch
    batch = DispatchBatchResult(
        mode=DispatchMode.FAILOVER.value,
        results=tuple(results),
        elapsed_ms=_now_ms() - started,
        total_attempted=len(results),
        total_succeeded=0,
        total_skipped=0,
    )
    if raise_on_all_fail:
        raise DispatcherAllFailedError(f"all {len(results)} candidates failed", batch)
    return batch


# ---------------------------------------------------------------------------
# Race
# ---------------------------------------------------------------------------


async def ainvoke_race(
    candidates: Iterable[DispatchCandidate],
    invoke: Callable[[DispatchCandidate], Awaitable[Any]],
    *,
    timeout_seconds: float | None = None,
    max_concurrency: int | None = None,
) -> DispatchBatchResult:
    """First successful response wins; slower tasks are cancelled."""
    if not race_allowed():
        raise DispatcherRaceDisabledError(
            "MODEL_DISPATCHER_ALLOW_RACE is disabled by env"
        )
    sorted_cands = _sort_by_priority(candidates)
    if not sorted_cands:
        raise DispatcherEmptyError("no candidates supplied")
    selected, skipped_filter = _select_top_n(sorted_cands, cap=max_concurrency)
    if not selected:
        raise DispatcherEmptyError("max_concurrency=0 left no eligible candidates")
    timeout = timeout_seconds if timeout_seconds is not None else default_timeout_seconds()

    started = _now_ms()
    tasks: dict[asyncio.Task, DispatchCandidate] = {}
    for c in selected:
        t = asyncio.create_task(_await_one(invoke, c, timeout))
        tasks[t] = c

    winner: DispatchResult | None = None
    losses: list[DispatchResult] = []

    try:
        while tasks:
            done, _pending = await asyncio.wait(
                tasks.keys(), return_when=asyncio.FIRST_COMPLETED
            )
            for t in done:
                cand = tasks.pop(t)
                try:
                    r = t.result()
                except asyncio.CancelledError:
                    continue
                except Exception as exc:  # noqa: BLE001 — race wraps each task in _await_one which already converts errors; this outer net catches the rare case where the task itself failed before _await_one could shape a result (e.g. cancellation interleaved with raise).
                    r = _make_error_result(cand, exc, 0.0)
                if r.success and winner is None:
                    winner = r
                else:
                    losses.append(r)
            if winner is not None:
                break
    finally:
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks.keys(), return_exceptions=True)

    results: list[DispatchResult] = []
    if winner is not None:
        results.append(winner)
    results.extend(losses)
    for c in skipped_filter:
        results.append(_make_skipped_result(c, "skipped_by_priority_filter"))

    return DispatchBatchResult(
        mode=DispatchMode.RACE.value,
        results=tuple(results),
        elapsed_ms=_now_ms() - started,
        total_attempted=len(selected),
        total_succeeded=1 if winner else 0,
        total_skipped=len(skipped_filter),
    )


# ---------------------------------------------------------------------------
# Fanout / Broadcast
# ---------------------------------------------------------------------------


async def _gather_concurrent(
    candidates: list[DispatchCandidate],
    invoke: Callable[[DispatchCandidate], Awaitable[Any]],
    timeout: float,
    max_concurrency: int,
) -> list[DispatchResult]:
    sem = asyncio.Semaphore(max_concurrency)

    async def _bounded(c: DispatchCandidate) -> DispatchResult:
        async with sem:
            return await _await_one(invoke, c, timeout)

    return await asyncio.gather(*[_bounded(c) for c in candidates])


async def ainvoke_fanout(
    candidates: Iterable[DispatchCandidate],
    invoke: Callable[[DispatchCandidate], Awaitable[Any]],
    *,
    timeout_seconds: float | None = None,
    max_concurrency: int | None = None,
) -> DispatchBatchResult:
    """Run all selected (top-N) candidates concurrently; return all results."""
    sorted_cands = _sort_by_priority(candidates)
    if not sorted_cands:
        raise DispatcherEmptyError("no candidates supplied")
    selected, skipped_filter = _select_top_n(sorted_cands, cap=max_concurrency)
    if not selected:
        raise DispatcherEmptyError("max_concurrency=0 left no eligible candidates")
    timeout = timeout_seconds if timeout_seconds is not None else default_timeout_seconds()

    started = _now_ms()
    cap = max_concurrency if max_concurrency is not None else max_concurrency_default()
    results = await _gather_concurrent(selected, invoke, timeout, cap)
    for c in skipped_filter:
        results.append(_make_skipped_result(c, "skipped_by_priority_filter"))

    return DispatchBatchResult(
        mode=DispatchMode.FANOUT.value,
        results=tuple(results),
        elapsed_ms=_now_ms() - started,
        total_attempted=len(selected),
        total_succeeded=sum(1 for r in results if r.success),
        total_skipped=len(skipped_filter),
    )


async def ainvoke_broadcast(
    candidates: Iterable[DispatchCandidate],
    invoke: Callable[[DispatchCandidate], Awaitable[Any]],
    *,
    timeout_seconds: float | None = None,
) -> DispatchBatchResult:
    """Run ALL candidates concurrently — no priority cap.

    Concurrency is bounded only by ``MODEL_DISPATCHER_MAX_CONCURRENCY`` to
    avoid a runaway fan-out, but no candidate is filtered.
    """
    sorted_cands = _sort_by_priority(candidates)
    if not sorted_cands:
        raise DispatcherEmptyError("no candidates supplied")
    timeout = timeout_seconds if timeout_seconds is not None else default_timeout_seconds()
    cap = max_concurrency_default()

    started = _now_ms()
    results = await _gather_concurrent(sorted_cands, invoke, timeout, cap)

    return DispatchBatchResult(
        mode=DispatchMode.BROADCAST.value,
        results=tuple(results),
        elapsed_ms=_now_ms() - started,
        total_attempted=len(sorted_cands),
        total_succeeded=sum(1 for r in results if r.success),
        total_skipped=0,
    )


# ---------------------------------------------------------------------------
# Parallel round (per-agent slots)
# ---------------------------------------------------------------------------


async def arun_parallel_round(
    agent_slots: Iterable[DispatchCandidate],
    invoke: Callable[[DispatchCandidate], Awaitable[Any]],
    *,
    timeout_seconds: float | None = None,
    max_concurrency: int | None = None,
) -> DispatchBatchResult:
    """Run one invocation per agent slot in parallel.

    Each slot must already have ``agent_id`` and ``role`` set on its
    ``DispatchCandidate`` so results can be matched back to the orchestrator's
    agent registry.

    No priority filter — every agent runs. Concurrency cap is per-call only
    (constraint #12).
    """
    slots = list(agent_slots)
    if not slots:
        raise DispatcherEmptyError("no agent slots supplied")
    missing = [s for s in slots if not s.agent_id]
    if missing:
        raise ValueError(
            f"agent_slot missing agent_id: {[s.candidate_id for s in missing]}"
        )
    timeout = timeout_seconds if timeout_seconds is not None else default_timeout_seconds()
    cap = max_concurrency if max_concurrency is not None else max_concurrency_default()

    started = _now_ms()
    results = await _gather_concurrent(slots, invoke, timeout, cap)

    return DispatchBatchResult(
        mode=DispatchMode.PARALLEL_ROUND.value,
        results=tuple(results),
        elapsed_ms=_now_ms() - started,
        total_attempted=len(slots),
        total_succeeded=sum(1 for r in results if r.success),
        total_skipped=0,
    )


__all__ = [
    "DispatchBatchResult",
    "DispatchCandidate",
    "DispatchErrorSummary",
    "DispatchMode",
    "DispatchResult",
    "DispatcherAllFailedError",
    "DispatcherEmptyError",
    "DispatcherError",
    "DispatcherRaceDisabledError",
    "ainvoke_broadcast",
    "ainvoke_failover",
    "ainvoke_fanout",
    "ainvoke_race",
    "arun_parallel_round",
    "default_timeout_seconds",
    "invoke_failover",
    "max_concurrency_default",
    "race_allowed",
]
