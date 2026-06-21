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

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from project_paths import runtime_state_path

# Defaults can be overridden via env if needed; conservative for desktop use.
DEFAULT_TTL_SECONDS = 24 * 60 * 60  # 24h
DEFAULT_CAPACITY = 100
DEFAULT_HISTORY_CAP = 100
DEFAULT_ARCHIVE_CAPACITY = 100
STORE_VERSION = 1


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
    event_log_start_index: int = 0


class DiscussionTaskStore:
    """Thread-safe in-memory store for discussion run state."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        capacity: int = DEFAULT_CAPACITY,
        history_cap: int = DEFAULT_HISTORY_CAP,
        archive_capacity: int = DEFAULT_ARCHIVE_CAPACITY,
        persistence_path: Path | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if history_cap <= 0:
            raise ValueError("history_cap must be positive")
        if archive_capacity <= 0:
            raise ValueError("archive_capacity must be positive")
        self._ttl = ttl_seconds
        self._capacity = capacity
        self._history_cap = history_cap
        self._archive_capacity = archive_capacity
        self._persistence_path = persistence_path
        self._lock = threading.RLock()
        self._entries: dict[str, _StoreEntry] = {}
        self._archived_entries: list[dict[str, Any]] = []
        self._load_persisted_state()

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    def register(self, run_id: str, config: dict[str, Any] | None = None) -> None:
        """Register a new run. Raises DiscussionTaskStoreFull at capacity."""
        with self._lock:
            self._sweep_locked()
            if len(self._entries) >= self._capacity:
                self._archive_oldest_terminal_locked()
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
            self._persist_locked()

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
            self._trim_event_log_locked(entry)
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
                    self._trim_live_traces_locked(entry)
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
            self._persist_locked()

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
            self._persist_locked()

    def get(self, run_id: str) -> dict[str, Any] | None:
        """Return a snapshot dict for the run, or None if absent / expired."""
        with self._lock:
            self._sweep_locked()
            entry = self._entries.get(run_id)
            if entry is None:
                return None
            return self._snapshot(entry)

    def get_any(self, run_id: str) -> dict[str, Any] | None:
        """Return a run snapshot from active history or archive."""
        if not run_id.strip():
            raise ValueError("run_id must not be empty")
        with self._lock:
            self._sweep_locked()
            entry = self._entries.get(run_id)
            if entry is not None:
                return self._snapshot(entry)
            archived = next(
                (dict(item) for item in self._archived_entries if item.get("run_id") == run_id),
                None,
            )
            return archived

    def get_event_log(self, run_id: str, from_index: int = 0) -> list[dict[str, Any]]:
        """Return events ≥ from_index for replay; empty if absent / out of range."""
        with self._lock:
            entry = self._entries.get(run_id)
            if entry is None:
                return []
            if from_index <= 0:
                return list(entry.event_log)
            if from_index <= entry.event_log_start_index:
                return list(entry.event_log)
            offset = from_index - entry.event_log_start_index
            return list(entry.event_log[offset:])

    def list_active(self) -> list[dict[str, Any]]:
        """Return snapshots of non-terminal runs (debugging / metrics)."""
        with self._lock:
            self._sweep_locked()
            return [
                self._snapshot(e)
                for e in self._entries.values()
                if e.state in ("pending", "running")
            ]

    def list_runs(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        """Return run snapshots ordered by newest update time."""
        with self._lock:
            self._sweep_locked()
            snapshots = [self._snapshot(entry) for entry in self._entries.values()]
            if include_archived:
                snapshots.extend(dict(entry) for entry in self._archived_entries)
            snapshots.sort(
                key=lambda item: (
                    float(item.get("updated_at", 0.0) or 0.0),
                    str(item.get("run_id", "")),
                ),
                reverse=True,
            )
            return snapshots

    def list_project_run_summaries(
        self,
        project_id: str,
        *,
        limit: int = 100,
        include_archived: bool = True,
    ) -> list[dict[str, Any]]:
        """Return project-scoped discussion metadata without answer bodies.

        Args:
            project_id: Discussion config project identifier.
            limit: Maximum run count; must be between 1 and 500.
            include_archived: Include capacity-archived snapshots.

        Returns:
            Run metadata and derived counts. Live traces, synthesis payloads,
            final result bodies, raw event logs, and error text are intentionally
            omitted because they may contain private model output or provider
            diagnostics.
        """

        normalized_project_id = str(project_id or "").strip()
        if not normalized_project_id:
            raise ValueError("project_id must not be empty")
        if not isinstance(limit, int) or limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        summaries: list[dict[str, Any]] = []
        for snapshot in self.list_runs(include_archived=include_archived):
            config = snapshot.get("config") if isinstance(snapshot.get("config"), dict) else {}
            if str(config.get("project_id") or "").strip() != normalized_project_id:
                continue
            agents = config.get("agents") or config.get("agent_configs")
            live_traces = snapshot.get("live_traces")
            summary = {
                "run_id": str(snapshot.get("run_id") or ""),
                "project_id": normalized_project_id,
                "query": str(config.get("query") or ""),
                "state": str(snapshot.get("state") or ""),
                "current_stage": str(snapshot.get("current_stage") or ""),
                "current_turn_index": int(snapshot.get("current_turn_index") or 0),
                "created_at_epoch": float(snapshot.get("created_at") or 0.0),
                "updated_at_epoch": float(snapshot.get("updated_at") or 0.0),
                "agent_count": len(agents) if isinstance(agents, list) else 0,
                "evidence_mode": str(config.get("evidence_mode") or ""),
                "evidence_top_k": int(config.get("evidence_top_k") or 0) if isinstance(config.get("evidence_top_k"), int) else 0,
                "live_trace_count": len(live_traces) if isinstance(live_traces, list) else 0,
                "event_log_length": int(snapshot.get("event_log_length") or 0),
                "event_log_start_index": int(snapshot.get("event_log_start_index") or 0),
                "has_synthesis": isinstance(snapshot.get("synthesis"), dict),
                "has_final_result": isinstance(snapshot.get("final_result"), dict),
                "has_error": bool(str(snapshot.get("error") or "").strip()),
                "archived": bool(snapshot.get("archived")),
            }
            summaries.append(summary)
            if len(summaries) >= limit:
                break
        return summaries

    def list_archived(self) -> list[dict[str, Any]]:
        """Return snapshots moved out by D11 capacity archiving."""
        with self._lock:
            return list(self._archived_entries)

    def archive(self, run_id: str) -> dict[str, Any] | None:
        """Move a run snapshot into the read-only archive."""
        with self._lock:
            entry = self._entries.pop(run_id, None)
            if entry is None:
                return None
            archived = self._snapshot(entry)
            archived["archived_at"] = time.time()
            archived["archived"] = True
            self._archived_entries.append(archived)
            overflow = len(self._archived_entries) - self._archive_capacity
            if overflow > 0:
                del self._archived_entries[:overflow]
            self._persist_locked()
            return archived

    def restore(self, run_id: str) -> dict[str, Any] | None:
        """Move an archived snapshot back into active discussion history."""
        if not run_id.strip():
            raise ValueError("run_id must not be empty")
        with self._lock:
            self._sweep_locked()
            existing = self._entries.get(run_id)
            if existing is not None:
                return self._snapshot(existing)
            archived_index = next(
                (
                    index
                    for index, item in enumerate(self._archived_entries)
                    if item.get("run_id") == run_id
                ),
                None,
            )
            if archived_index is None:
                return None
            if len(self._entries) >= self._capacity:
                self._archive_oldest_terminal_locked()
                if len(self._entries) >= self._capacity:
                    raise DiscussionTaskStoreFull(
                        f"discussion task store full: capacity={self._capacity}"
                    )
            archived = dict(self._archived_entries.pop(archived_index))
            archived.pop("archived", None)
            archived.pop("archived_at", None)
            archived["updated_at"] = time.time()
            entry = self._entry_from_raw(archived)
            if entry is None:
                return None
            self._entries[run_id] = entry
            self._persist_locked()
            return self._snapshot(entry)

    def delete(self, run_id: str, *, include_archived: bool = True) -> bool:
        with self._lock:
            removed = self._entries.pop(run_id, None) is not None
            if include_archived:
                before = len(self._archived_entries)
                self._archived_entries = [
                    entry for entry in self._archived_entries if entry.get("run_id") != run_id
                ]
                removed = removed or len(self._archived_entries) != before
            self._persist_locked()
            return removed

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._archived_entries.clear()
            self._persist_locked()

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
        if expired:
            self._persist_locked()

    def _trim_event_log_locked(self, entry: _StoreEntry) -> None:
        """Keep newest replay events within the configured D10 history cap."""
        overflow = len(entry.event_log) - self._history_cap
        if overflow <= 0:
            return
        del entry.event_log[:overflow]
        entry.event_log_start_index += overflow

    def _trim_live_traces_locked(self, entry: _StoreEntry) -> None:
        """Keep newest live traces within the configured D10 history cap."""
        overflow = len(entry.live_traces) - self._history_cap
        if overflow > 0:
            del entry.live_traces[:overflow]

    def _archive_oldest_terminal_locked(self) -> None:
        """Move the oldest terminal run into the D11 archive when capacity is full."""
        terminal_entries = [
            entry
            for entry in self._entries.values()
            if entry.state in ("completed", "cancelled", "error")
        ]
        if not terminal_entries:
            return
        oldest = min(terminal_entries, key=lambda entry: (entry.updated_at, entry.created_at, entry.run_id))
        archived = self._snapshot(oldest)
        archived["archived_at"] = time.time()
        archived["archived"] = True
        self._archived_entries.append(archived)
        overflow = len(self._archived_entries) - self._archive_capacity
        if overflow > 0:
            del self._archived_entries[:overflow]
        self._entries.pop(oldest.run_id, None)

    def _load_persisted_state(self) -> None:
        """Load D17 persisted store state from disk when configured."""
        path = self._persistence_path
        if path is None or not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return

        raw_entries = payload.get("entries")
        if isinstance(raw_entries, list):
            for raw_entry in raw_entries:
                entry = self._entry_from_raw(raw_entry)
                if entry is not None:
                    self._entries[entry.run_id] = entry

        raw_archive = payload.get("archived_entries")
        if isinstance(raw_archive, list):
            self._archived_entries = [item for item in raw_archive if isinstance(item, dict)][-self._archive_capacity:]
        self._sweep_locked()

    def _persist_locked(self) -> None:
        """Persist D17 store state with tmp+replace semantics when configured."""
        path = self._persistence_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": STORE_VERSION,
            "entries": [self._entry_to_raw(entry) for entry in self._entries.values()],
            "archived_entries": list(self._archived_entries),
        }
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp_path, path)

    @staticmethod
    def _entry_to_raw(entry: _StoreEntry) -> dict[str, Any]:
        """Serialize one task-store entry for D17 runtime persistence."""
        return {
            "run_id": entry.run_id,
            "state": entry.state,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "config": entry.config,
            "current_stage": entry.current_stage,
            "current_turn_index": entry.current_turn_index,
            "live_traces": list(entry.live_traces),
            "synthesis": entry.synthesis,
            "final_result": entry.final_result,
            "error": entry.error,
            "event_log": list(entry.event_log),
            "event_log_start_index": entry.event_log_start_index,
        }

    @staticmethod
    def _entry_from_raw(raw_entry: Any) -> _StoreEntry | None:
        """Parse one persisted D17 entry, skipping malformed artifacts."""
        if not isinstance(raw_entry, dict):
            return None
        run_id = raw_entry.get("run_id")
        state = raw_entry.get("state")
        created_at = raw_entry.get("created_at")
        updated_at = raw_entry.get("updated_at")
        if not isinstance(run_id, str) or not run_id.strip():
            return None
        if state not in ("pending", "running", "completed", "cancelled", "error"):
            return None
        if not isinstance(created_at, (int, float)) or not isinstance(updated_at, (int, float)):
            return None
        config = raw_entry.get("config") if isinstance(raw_entry.get("config"), dict) else None
        live_traces = raw_entry.get("live_traces") if isinstance(raw_entry.get("live_traces"), list) else []
        event_log = raw_entry.get("event_log") if isinstance(raw_entry.get("event_log"), list) else []
        return _StoreEntry(
            run_id=run_id,
            state=state,
            created_at=float(created_at),
            updated_at=float(updated_at),
            config=config,
            current_stage=raw_entry.get("current_stage") if isinstance(raw_entry.get("current_stage"), str) else None,
            current_turn_index=raw_entry.get("current_turn_index") if isinstance(raw_entry.get("current_turn_index"), int) else 0,
            live_traces=[item for item in live_traces if isinstance(item, dict)],
            synthesis=raw_entry.get("synthesis") if isinstance(raw_entry.get("synthesis"), dict) else None,
            final_result=raw_entry.get("final_result") if isinstance(raw_entry.get("final_result"), dict) else None,
            error=raw_entry.get("error") if isinstance(raw_entry.get("error"), str) else None,
            event_log=[item for item in event_log if isinstance(item, dict)],
            event_log_start_index=raw_entry.get("event_log_start_index") if isinstance(raw_entry.get("event_log_start_index"), int) else 0,
        )

    def _snapshot(self, entry: _StoreEntry) -> dict[str, Any]:
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
            "config": entry.config,
            "event_log_length": len(entry.event_log),
            "event_log_start_index": entry.event_log_start_index,
            "history_cap": self._history_cap,
            "archived": False,
        }


# ---------------------------------------------------------------------------
# Process-wide singleton (the FastAPI app shares one store across requests).
# Endpoint code imports ``get_discussion_task_store()``.
# ---------------------------------------------------------------------------

_singleton: DiscussionTaskStore | None = None
_singleton_lock = threading.Lock()


def discussion_task_store_path() -> Path:
    """Return the D17 durable task-store path under runtime state."""
    return runtime_state_path("discussion", "task_store.json")


def get_discussion_task_store() -> DiscussionTaskStore:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = DiscussionTaskStore(persistence_path=discussion_task_store_path())
    return _singleton


def reset_discussion_task_store_for_tests(
    persistence_path: Path | None = None,
) -> None:
    """Test-only: reset the singleton between test cases."""
    global _singleton
    with _singleton_lock:
        _singleton = (
            DiscussionTaskStore(persistence_path=persistence_path)
            if persistence_path is not None
            else None
        )
