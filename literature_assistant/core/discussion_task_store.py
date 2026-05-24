"""Discussion task persistence store (B1 / 0.1.8.2).

Cross-page-reload persistence for multi-agent discussion runs. Designed to
solve the user-reported issue (2026-05-23): "切换界面就丢了/不能因为切换界面
就从头开始思考".

Architecture (per docs/plans/active/2026-05-24-0182-B1-discussion-task-
persistence-plan.md):

- In-memory dict keyed by ``run_id``; each entry holds the rolling state
  emitted by the orchestrator's ``on_event`` callback plus terminal
  ``final_result`` / ``error``.
- TTL 24h; entries past TTL are swept on each access (no background thread).
- Capacity limit 100 active runs to bound memory; new ``register`` while at
  capacity raises ``DiscussionTaskStoreFull`` (the endpoint maps this to 503).
- Thread-safe via ``threading.RLock`` (the FastAPI app may handle the SSE
  generator and the GET endpoint on different worker threads under uvicorn).
- Survives router/orchestrator restarts within the same process. Does NOT
  survive Python process restart (B1.future would add SQLite for that).

Run lifecycle:

    register(run_id, config) -> state = "pending"
    update(run_id, state="running", current_stage="retrieval")
    update(run_id, ..., trace=...)    # append per agent_done
    update(run_id, state="completed", final_result=...)
    # later
    get(run_id)  -> RunState dict
    # eventually
    expire / 24h sweep / capacity overflow → entry removed
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

# Defaults can be overridden via env if needed; conservative for desktop use.
DEFAULT_TTL_SECONDS = 24 * 60 * 60  # 24h
DEFAULT_CAPACITY = 100


class DiscussionTaskStoreError(Exception):
    """Base error for the discussion task store."""


class DiscussionTaskStoreFull(DiscussionTaskStoreError):
    """Raised when capacity exceeded; caller should return 503."""


@dataclass
class _StoreEntry:
    run_id: str
    state: str  # "pending" | "running" | "completed" | "cancelled" | "error"
    created_at: float
    updated_at: float
    config: dict[str, Any] | None
    current_stage: str | None = None
    current_turn_index: int = 0
    live_traces: list[dict[str, Any]] = field(default_factory=list)
    synthesis: dict[str, Any] | None = None
    final_result: dict[str, Any] | None = None
    error: str | None = None
    # Event log so a resuming consumer can replay missed events from index N.
    # Each entry is the raw event dict as emitted to the SSE stream.
    event_log: list[dict[str, Any]] = field(default_factory=list)


class DiscussionTaskStore:
    """Thread-safe in-memory store for discussion run state."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        capacity: int = DEFAULT_CAPACITY,
    ) -> None:
        self._ttl = ttl_seconds
        self._capacity = capacity
        self._lock = threading.RLock()
        self._entries: dict[str, _StoreEntry] = {}

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    def register(self, run_id: str, config: dict[str, Any] | None = None) -> None:
        """Register a new run. Raises DiscussionTaskStoreFull at capacity."""
        with self._lock:
            self._sweep_locked()
            if len(self._entries) >= self._capacity:
                raise DiscussionTaskStoreFull(
                    f"discussion task store at capacity ({self._capacity})"
                )
            if run_id in self._entries:
                raise DiscussionTaskStoreError(f"run_id already registered: {run_id}")
            now = time.time()
            self._entries[run_id] = _StoreEntry(
                run_id=run_id,
                state="pending",
                created_at=now,
                updated_at=now,
                config=config,
            )

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        """Record a raw event for replay AND apply derived state.

        Idempotent on absent run_id (we don't want orchestrator emit failures
        to crash if the store entry was purged mid-run).
        """
        with self._lock:
            entry = self._entries.get(run_id)
            if entry is None:
                return
            entry.event_log.append(event)
            entry.updated_at = time.time()
            kind = event.get("event")
            if kind == "started":
                entry.state = "running"
                stage = event.get("stage")
                if isinstance(stage, str):
                    entry.current_stage = stage
            elif kind == "stage_progress":
                stage = event.get("stage")
                if isinstance(stage, str):
                    entry.current_stage = stage
            elif kind == "agent_done":
                trace = event.get("trace")
                if isinstance(trace, dict):
                    entry.live_traces.append(trace)
                turn_idx = event.get("turn_index")
                if isinstance(turn_idx, int) and turn_idx > entry.current_turn_index:
                    entry.current_turn_index = turn_idx
            elif kind == "turn_done":
                turn_idx = event.get("turn_index")
                if isinstance(turn_idx, int) and turn_idx > entry.current_turn_index:
                    entry.current_turn_index = turn_idx
            elif kind == "synthesis_done":
                synth = event.get("synthesis")
                if isinstance(synth, dict):
                    entry.synthesis = synth
            elif kind == "done":
                entry.state = "completed"
                result = event.get("result")
                if isinstance(result, dict):
                    entry.final_result = result
            elif kind == "error":
                entry.state = "error"
                err = event.get("error")
                if isinstance(err, str):
                    entry.error = err

    def mark_terminal(self, run_id: str, state: str, error: str | None = None) -> None:
        """Force terminal state (e.g. on orchestrator exception that bypassed
        the event log path).
        """
        if state not in ("completed", "cancelled", "error"):
            raise ValueError(f"invalid terminal state: {state}")
        with self._lock:
            entry = self._entries.get(run_id)
            if entry is None:
                return
            entry.state = state
            entry.updated_at = time.time()
            if error and not entry.error:
                entry.error = error

    def get(self, run_id: str) -> dict[str, Any] | None:
        """Return a snapshot dict for the run, or None if absent / expired."""
        with self._lock:
            self._sweep_locked()
            entry = self._entries.get(run_id)
            if entry is None:
                return None
            return self._snapshot(entry)

    def get_event_log(self, run_id: str, from_index: int = 0) -> list[dict[str, Any]]:
        """Return events ≥ from_index for replay; empty if absent / out of range."""
        with self._lock:
            entry = self._entries.get(run_id)
            if entry is None:
                return []
            if from_index <= 0:
                return list(entry.event_log)
            return list(entry.event_log[from_index:])

    def list_active(self) -> list[dict[str, Any]]:
        """Return snapshots of non-terminal runs (debugging / metrics)."""
        with self._lock:
            self._sweep_locked()
            return [
                self._snapshot(e)
                for e in self._entries.values()
                if e.state in ("pending", "running")
            ]

    def delete(self, run_id: str) -> None:
        with self._lock:
            self._entries.pop(run_id, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    # ---------------------------------------------------------------------
    # Internal
    # ---------------------------------------------------------------------

    def _sweep_locked(self) -> None:
        """Remove expired entries. Caller must hold the lock."""
        if not self._entries:
            return
        cutoff = time.time() - self._ttl
        expired = [rid for rid, e in self._entries.items() if e.updated_at < cutoff]
        for rid in expired:
            del self._entries[rid]

    @staticmethod
    def _snapshot(entry: _StoreEntry) -> dict[str, Any]:
        return {
            "run_id": entry.run_id,
            "state": entry.state,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "current_stage": entry.current_stage,
            "current_turn_index": entry.current_turn_index,
            "live_traces": list(entry.live_traces),
            "synthesis": entry.synthesis,
            "final_result": entry.final_result,
            "error": entry.error,
            "event_log_length": len(entry.event_log),
        }


# ---------------------------------------------------------------------------
# Process-wide singleton (the FastAPI app shares one store across requests).
# Endpoint code imports ``get_discussion_task_store()``.
# ---------------------------------------------------------------------------

_singleton: DiscussionTaskStore | None = None
_singleton_lock = threading.Lock()


def get_discussion_task_store() -> DiscussionTaskStore:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = DiscussionTaskStore()
    return _singleton


def reset_discussion_task_store_for_tests() -> None:
    """Test-only: reset the singleton between test cases."""
    global _singleton
    with _singleton_lock:
        _singleton = None
