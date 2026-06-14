# -*- coding: utf-8 -*-
"""
WritingRuntime - Long-lived backend runtime for session and job management.

Manages WritingSession, WritingJob, WritingEvent, and WritingArtifact.
Provides stable in-memory state management with clean interfaces for future persistence.
Maintains backward compatibility with legacy run_action flows.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import os
import sqlite3
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from datetime_utils import utc_now_iso_z
from repositories.writing_runtime_repository import WritingRuntimeRepository
from harness_protocols import (
    WritingSession,
    WritingJob,
    WritingEvent,
    WritingArtifact,
    WritingApprovalRequest,
    SessionMode,
    JobKind,
    JobStatus,
    EventType,
    ArtifactType,
    ApprovalStatus,
)
from skills.runtime import SkillRunResult

logger = logging.getLogger("WritingRuntime")

_RUNTIME_RECOVERABLE_EXCEPTIONS = (
    AssertionError,
    AttributeError,
    BufferError,
    EOFError,
    ExceptionGroup,
    ImportError,
    IndexError,
    KeyError,
    LookupError,
    MemoryError,
    NameError,
    NotImplementedError,
    OSError,
    ReferenceError,
    RuntimeError,
    TypeError,
    ValueError,
)


def _is_http_like_exception(exc: BaseException) -> bool:
    """Return True for FastAPI/Starlette HTTPException-like errors.

    We can't add HTTPException to the recoverable tuple directly because
    importing fastapi at module load adds startup cost. Detect by class name
    walking the MRO so both ``fastapi.HTTPException`` and
    ``starlette.exceptions.HTTPException`` (the former's parent) match.
    """
    for cls in type(exc).__mro__:
        if cls.__name__ == "HTTPException":
            return True
    return False


def _format_http_exception(exc: BaseException) -> str:
    """Render an HTTPException for the job error string."""
    status = getattr(exc, "status_code", None)
    detail = getattr(exc, "detail", None)
    if status and detail:
        return f"HTTP {status}: {detail}"
    if detail:
        return str(detail)
    return str(exc)


def _resolve_workspace_root(entry_cwd: str | Path | None = None) -> Path:
    """Resolve the workspace root, preferring a parent git root when present."""
    candidate = Path(entry_cwd or Path.cwd()).expanduser().resolve()
    for parent in (candidate, *candidate.parents):
        if (parent / ".git").exists():
            return parent
    return candidate


def _default_runtime_storage_root() -> Path:
    """Return the default workspace-local storage root for runtime persistence."""
    configured_root = os.environ.get("WRITING_RUNTIME_STORAGE_ROOT", "").strip()
    if configured_root:
        return Path(configured_root).expanduser().resolve()

    try:
        from project_paths import runtime_state_path

        return runtime_state_path("writing_runtime")
    except Exception:
        return _resolve_workspace_root() / ".modular" / "sessions"


def _stable_workspace_key(workspace_root: Path) -> str:
    """Build a stable workspace key from a normalized root path."""
    return hashlib.sha256(str(workspace_root).encode("utf-8")).hexdigest()


def _default_runtime_db_path() -> Path:
    """Resolve the default SQLite path for the runtime singleton."""
    configured_path = os.environ.get("WRITING_RUNTIME_DB_PATH", "").strip()
    if configured_path:
        return Path(configured_path).expanduser().resolve()
    return _default_runtime_storage_root() / "index.sqlite3"


@dataclass
class JobExecutionContext:
    """Context for executing a job with runtime state."""
    job: WritingJob
    execution_state: dict[str, Any] = field(default_factory=dict)
    is_paused: bool = False
    is_cancelled: bool = False
    pause_event: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self):
        """Initialize async events if not already set."""
        if not isinstance(self.pause_event, asyncio.Event):
            self.pause_event = asyncio.Event()
        if not isinstance(self.cancel_event, asyncio.Event):
            self.cancel_event = asyncio.Event()
        self.pause_event.set()  # Start as not paused


class WritingRuntime:
    """
    Long-lived backend runtime managing sessions, jobs, events, and artifacts.
    
    Responsibilities:
    - Manage session lifecycle and context
    - Queue, execute, pause, resume, and cancel jobs
    - Emit events for state transitions
    - Store artifacts from job execution
    - Maintain approval gates
    
    In-memory state: Clean interfaces support future persistence to database or file system.
    """

    def __init__(self, database_path: str | Path | None = None, autosave: bool = False):
        """Initialize runtime with empty state and optional SQLite persistence."""
        self._sessions: dict[str, WritingSession] = {}
        self._jobs: dict[str, WritingJob] = {}
        self._job_queue: list[str] = []  # job_ids in order
        self._job_contexts: dict[str, JobExecutionContext] = {}
        self._events: dict[str, list[WritingEvent]] = {}  # events by session_id
        self._artifacts: dict[str, list[WritingArtifact]] = {}  # artifacts by job_id
        self._approval_requests: dict[str, WritingApprovalRequest] = {}
        self._event_subscribers: dict[str, list[Callable]] = {}  # session_id -> callbacks
        self._session_transcripts: dict[str, list[dict[str, Any]]] = {}
        self._session_checkpoints: dict[str, list[dict[str, Any]]] = {}
        self._job_tasks: dict[str, asyncio.Task[Any]] = {}
        self._logger = logging.getLogger(f"{__name__}.{id(self)}")
        self._memory_adapter: Any | None = None
        self._memory_adapter_resolved = False
        self._database_path = Path(database_path).resolve() if database_path is not None else None
        self._repository = None
        if self._database_path is not None:
            try:
                self._repository = WritingRuntimeRepository(self._database_path)
            except (OSError, sqlite3.Error) as exc:
                self._logger.warning("Unable to open SQLite runtime repository at %s: %s", self._database_path, exc)
        self._autosave = autosave and self._repository is not None

        if self._repository is not None and self._repository.is_healthy() and self._repository.has_data():
            self.load_from_database()

    # ==========================================================================
    # Session Management
    # ==========================================================================

    def create_session(
        self,
        mode: SessionMode,
        user_id: str | None = None,
        settings: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WritingSession:
        """Create a new writing session."""
        normalized_metadata = self._normalize_session_metadata(metadata)
        session = WritingSession.create(
            mode=mode,
            user_id=user_id,
            settings=settings,
            tags=tags,
            metadata=normalized_metadata,
        )
        self._sessions[session.session_id] = session
        self._events[session.session_id] = []
        self._session_transcripts[session.session_id] = []
        self._session_checkpoints[session.session_id] = []
        self._append_transcript_event(
            session.session_id,
            "session_created",
            {
                "session_id": session.session_id,
                "title": session.metadata.get("title", "Untitled session"),
                "workspace_root": session.metadata["workspace_root"],
                "workspace_key": session.metadata["workspace_key"],
                "entry_cwd": session.metadata["entry_cwd"],
            },
        )
        self._create_checkpoint(session.session_id, kind="session_created")
        self._logger.info("Created session %s with mode %s", session.session_id, mode.value)
        self._autosave_if_enabled()
        return session

    def get_session(self, session_id: str) -> WritingSession | None:
        """Retrieve a session by ID."""
        return self._sessions.get(session_id)

    def list_sessions(
        self,
        user_id: str | None = None,
        workspace_key: str | None = None,
        include_archived: bool = False,
    ) -> list[WritingSession]:
        """List sessions, optionally filtered by user and workspace."""
        sessions = list(self._sessions.values())
        if user_id:
            sessions = [s for s in sessions if s.user_id == user_id]
        if workspace_key:
            sessions = [s for s in sessions if s.metadata.get("workspace_key") == workspace_key]
        if not include_archived:
            sessions = [s for s in sessions if s.metadata.get("status", "active") != "archived"]
        sessions.sort(key=lambda session: session.metadata.get("updated_at", session.created_at), reverse=True)
        return sessions

    def get_current_session(
        self,
        workspace_root: str | Path | None = None,
        workspace_key: str | None = None,
        entry_cwd: str | Path | None = None,
    ) -> WritingSession | None:
        """Return the most recently active session for a workspace binding."""
        resolved_workspace_key = workspace_key
        if resolved_workspace_key is None:
            root_candidate = Path(workspace_root).expanduser().resolve() if workspace_root else _resolve_workspace_root(entry_cwd)
            resolved_workspace_key = _stable_workspace_key(root_candidate)
        sessions = self.list_sessions(workspace_key=resolved_workspace_key)
        return sessions[0] if sessions else None

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and all runtime state owned by it.

        Args:
            session_id: Existing runtime session identifier.

        Returns:
            True when a session was deleted; False when it did not exist.

        Raises:
            ValueError: If ``session_id`` is blank.
        """
        normalized = str(session_id or "").strip()
        if not normalized:
            raise ValueError("session_id must not be empty")
        if normalized not in self._sessions:
            return False

        job_ids = [
            job_id
            for job_id, job in self._jobs.items()
            if job.session_id == normalized
        ]
        approval_ids = [
            approval_id
            for approval_id, approval in self._approval_requests.items()
            if approval.session_id == normalized
        ]

        self._sessions.pop(normalized, None)
        self._events.pop(normalized, None)
        self._session_transcripts.pop(normalized, None)
        self._session_checkpoints.pop(normalized, None)
        self._event_subscribers.pop(normalized, None)
        for job_id in job_ids:
            self._jobs.pop(job_id, None)
            self._job_contexts.pop(job_id, None)
            self._artifacts.pop(job_id, None)
        job_id_set = set(job_ids)
        self._job_queue = [job_id for job_id in self._job_queue if job_id not in job_id_set]
        for approval_id in approval_ids:
            self._approval_requests.pop(approval_id, None)

        if self._repository is not None:
            self._repository.delete_session(normalized)
        self._autosave_if_enabled()
        self._logger.info("Deleted session %s", normalized)
        return True

    def resume_session(
        self,
        session_id: str | None = None,
        workspace_root: str | Path | None = None,
        workspace_key: str | None = None,
        entry_cwd: str | Path | None = None,
    ) -> dict[str, Any]:
        """Resume a session by ID or current workspace binding."""
        session = self.get_session(session_id) if session_id else self.get_current_session(
            workspace_root=workspace_root,
            workspace_key=workspace_key,
            entry_cwd=entry_cwd,
        )
        if session is None:
            raise ValueError("No resumable session found")
        timeline = self.get_session_timeline(session.session_id, limit=100)
        return {
            "session": session.to_dict(),
            "head_event_id": session.metadata.get("head_event_id"),
            "head_checkpoint_id": session.metadata.get("head_checkpoint_id"),
            "timeline": timeline["items"],
            "next_cursor": timeline["next_cursor"],
        }

    def get_session_timeline(
        self,
        session_id: str,
        after_event_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return the active transcript lineage for a session with cursor pagination."""
        active_timeline = self._get_active_transcript(session_id)
        if after_event_id is not None:
            cursor_index = next(
                (index for index, event in enumerate(active_timeline) if event["event_id"] == after_event_id),
                None,
            )
            if cursor_index is not None:
                active_timeline = active_timeline[cursor_index + 1 :]
        items = active_timeline[:limit]
        next_cursor = items[-1]["event_id"] if len(active_timeline) > limit and items else None
        session = self.get_session(session_id)
        return {
            "session_id": session_id,
            "head_event_id": session.metadata.get("head_event_id") if session else None,
            "items": items,
            "next_cursor": next_cursor,
        }

    def list_checkpoints(self, session_id: str) -> list[dict[str, Any]]:
        """List checkpoints for a session, annotating active lineage membership."""
        active_event_ids = {event["event_id"] for event in self._get_active_transcript(session_id)}
        checkpoints = []
        for checkpoint in self._session_checkpoints.get(session_id, []):
            enriched = dict(checkpoint)
            enriched["active"] = checkpoint["event_id"] in active_event_ids
            checkpoints.append(enriched)
        checkpoints.sort(key=lambda item: item["created_at"])
        return checkpoints

    def rewind_session(self, session_id: str, checkpoint_id: str, mode: str = "conversation_only") -> dict[str, Any]:
        """Rewind the active session head back to a stored checkpoint lineage."""
        checkpoint = self._get_checkpoint(session_id, checkpoint_id)
        if checkpoint is None:
            raise ValueError(f"Checkpoint {checkpoint_id} not found for session {session_id}")
        self._append_transcript_event(
            session_id,
            "session_rewound",
            {
                "checkpoint_id": checkpoint_id,
                "mode": mode,
                "workspace_restore_supported": mode != "conversation_only",
                "workspace_restore_limited": mode != "conversation_only",
            },
            parent_event_id=checkpoint["event_id"],
        )
        self._replace_session_metadata(session_id, head_checkpoint_id=checkpoint_id)
        self._autosave_if_enabled()
        return self.resume_session(session_id=session_id)

    def fork_session(
        self,
        session_id: str,
        checkpoint_id: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Create a branch session seeded from an existing checkpoint lineage."""
        source_session = self.get_session(session_id)
        if source_session is None:
            raise ValueError(f"Session {session_id} not found")
        checkpoint = self._get_checkpoint(session_id, checkpoint_id)
        if checkpoint is None:
            raise ValueError(f"Checkpoint {checkpoint_id} not found for session {session_id}")

        source_lineage = self._get_lineage_to_event(session_id, checkpoint["event_id"])
        source_checkpoint_map = {
            item["event_id"]: item
            for item in self._session_checkpoints.get(session_id, [])
            if item["event_id"] in {event["event_id"] for event in source_lineage}
        }

        fork_metadata = self._normalize_session_metadata(
            {
                **dict(source_session.metadata),
                "title": title or f"{source_session.metadata.get('title', 'Session')} (fork)",
                "parent_session_id": session_id,
                "forked_from_checkpoint_id": checkpoint_id,
                "forked_from_turn_id": checkpoint["metadata"].get("source_job_id"),
            }
        )
        fork_metadata["head_event_id"] = None
        fork_metadata["head_checkpoint_id"] = None
        forked_session = WritingSession.create(
            mode=source_session.mode,
            user_id=source_session.user_id,
            settings=dict(source_session.settings),
            tags=list(source_session.tags),
            metadata=fork_metadata,
        )
        self._sessions[forked_session.session_id] = forked_session
        self._events[forked_session.session_id] = []
        self._session_transcripts[forked_session.session_id] = []
        self._session_checkpoints[forked_session.session_id] = []

        event_id_map: dict[str, str] = {}
        copied_transcript: list[dict[str, Any]] = []
        copied_checkpoints: list[dict[str, Any]] = []
        for source_event in source_lineage:
            new_event_id = f"evt_{os.urandom(8).hex()}"
            event_id_map[source_event["event_id"]] = new_event_id
            copied_transcript.append(
                {
                    **source_event,
                    "event_id": new_event_id,
                    "session_id": forked_session.session_id,
                    "parent_event_id": event_id_map.get(source_event.get("parent_event_id")),
                }
            )
            source_checkpoint = source_checkpoint_map.get(source_event["event_id"])
            if source_checkpoint is not None:
                copied_checkpoints.append(
                    {
                        "checkpoint_id": f"chk_{os.urandom(8).hex()}",
                        "session_id": forked_session.session_id,
                        "event_id": new_event_id,
                        "created_at": source_checkpoint["created_at"],
                        "kind": source_checkpoint["kind"],
                        "metadata": {
                            **dict(source_checkpoint.get("metadata") or {}),
                            "source_checkpoint_id": source_checkpoint["checkpoint_id"],
                        },
                    }
                )

        self._session_transcripts[forked_session.session_id] = copied_transcript
        self._session_checkpoints[forked_session.session_id] = copied_checkpoints
        copied_target_checkpoint = next(
            (
                item
                for item in copied_checkpoints
                if item["metadata"].get("source_checkpoint_id") == checkpoint_id
            ),
            None,
        )
        self._replace_session_metadata(
            forked_session.session_id,
            head_event_id=event_id_map[checkpoint["event_id"]],
            head_checkpoint_id=copied_target_checkpoint["checkpoint_id"] if copied_target_checkpoint else None,
        )
        if self._repository is not None:
            self._repository.replace_transcript(forked_session.session_id, copied_transcript)

        self._append_transcript_event(
            forked_session.session_id,
            "session_forked",
            {
                "source_session_id": session_id,
                "source_checkpoint_id": checkpoint_id,
            },
            parent_event_id=event_id_map[checkpoint["event_id"]],
        )
        self._create_checkpoint(forked_session.session_id, kind="session_forked")
        self._autosave_if_enabled()
        return self.resume_session(session_id=forked_session.session_id)

    # ==========================================================================
    # Job Management
    # ==========================================================================

    def create_job(
        self,
        session_id: str,
        kind: JobKind,
        input_text: str = "",
        action_id: str | None = None,
        skill_id: str | None = None,
        scope: str | None = None,
        output_mode: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WritingJob:
        """Create a new job in a session."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        job = WritingJob.create(
            session_id=session_id,
            kind=kind,
            input_text=input_text,
            action_id=action_id,
            skill_id=skill_id,
            scope=scope,
            output_mode=output_mode,
            tags=tags,
            metadata=metadata,
        )

        self._jobs[job.job_id] = job
        self._job_queue.append(job.job_id)
        self._job_contexts[job.job_id] = JobExecutionContext(job=job)
        self._artifacts[job.job_id] = []

        # Emit job created event
        self._emit_event(
            session_id,
            WritingEvent.create(
                job_id=job.job_id,
                session_id=session_id,
                event_type=EventType.JOB_CREATED,
                data={
                    "job_id": job.job_id,
                    "kind": kind.value,
                    "input_text": input_text,
                    "action_id": action_id,
                    "skill_id": skill_id,
                },
            ),
        )

        self._logger.info("Created job %s in session %s", job.job_id, session_id)
        return job

    def get_job(self, job_id: str) -> WritingJob | None:
        """Retrieve a job by ID."""
        return self._jobs.get(job_id)

    def delete_job(self, job_id: str) -> bool:
        """Delete a job and all runtime data owned by that job.

        Args:
            job_id: Existing runtime job identifier.

        Returns:
            True when the job existed and was removed; False when it was absent.

        Raises:
            ValueError: If ``job_id`` is blank.
        """
        normalized = str(job_id or "").strip()
        if not normalized:
            raise ValueError("job_id must not be empty")
        job = self._jobs.get(normalized)
        if job is None:
            return False

        task = self._job_tasks.pop(normalized, None)
        if task is not None and not task.done():
            task.cancel()

        session_id = job.session_id
        self._jobs.pop(normalized, None)
        self._job_contexts.pop(normalized, None)
        self._artifacts.pop(normalized, None)
        self._job_queue = [queued_id for queued_id in self._job_queue if queued_id != normalized]
        self._approval_requests = {
            approval_id: approval
            for approval_id, approval in self._approval_requests.items()
            if approval.job_id != normalized
        }
        self._events[session_id] = [
            event
            for event in self._events.get(session_id, [])
            if event.job_id != normalized
        ]
        self._session_checkpoints[session_id] = [
            checkpoint
            for checkpoint in self._session_checkpoints.get(session_id, [])
            if dict(checkpoint.get("metadata") or {}).get("source_job_id") != normalized
        ]

        self._ensure_transcript_loaded(session_id)
        filtered_transcript = [
            event
            for event in self._session_transcripts.get(session_id, [])
            if not self._transcript_event_references_job(event, normalized)
        ]
        self._session_transcripts[session_id] = filtered_transcript
        if self.get_session(session_id) is not None:
            remaining_checkpoint_ids = {
                str(checkpoint.get("checkpoint_id"))
                for checkpoint in self._session_checkpoints.get(session_id, [])
            }
            current_session = self.get_session(session_id)
            current_head_event_id = str(current_session.metadata.get("head_event_id") or "") if current_session else ""
            current_head_checkpoint_id = str(current_session.metadata.get("head_checkpoint_id") or "") if current_session else ""
            remaining_event_ids = {
                str(event.get("event_id"))
                for event in filtered_transcript
                if isinstance(event, dict)
            }
            metadata_updates: dict[str, Any] = {}
            if current_head_event_id and current_head_event_id not in remaining_event_ids:
                metadata_updates["head_event_id"] = filtered_transcript[-1]["event_id"] if filtered_transcript else None
            if current_head_checkpoint_id and current_head_checkpoint_id not in remaining_checkpoint_ids:
                checkpoints = self._session_checkpoints.get(session_id, [])
                metadata_updates["head_checkpoint_id"] = checkpoints[-1]["checkpoint_id"] if checkpoints else None
            if metadata_updates:
                self._replace_session_metadata(session_id, **metadata_updates)
            if self._repository is not None:
                self._repository.replace_transcript(session_id, filtered_transcript)

        self._autosave_if_enabled()
        self._logger.info("Deleted job %s and its runtime data", normalized)
        return True

    @staticmethod
    def _transcript_event_references_job(event: dict[str, Any], job_id: str) -> bool:
        """Return True when a transcript event belongs to the target job."""
        if not isinstance(event, dict):
            return False
        payload = event.get("payload")
        if isinstance(payload, dict):
            if str(payload.get("job_id") or "") == job_id:
                return True
            if str(payload.get("source_job_id") or "") == job_id:
                return True
        return False

    def list_jobs(self, session_id: str, status: JobStatus | None = None) -> list[WritingJob]:
        """List all jobs in a session, optionally filtered by status."""
        jobs = [j for j in self._jobs.values() if j.session_id == session_id]
        if status:
            jobs = [j for j in jobs if j.status == status]
        return jobs

    def query_job_status(self, job_id: str) -> dict[str, Any]:
        """Query current job status with detailed information."""
        job = self.get_job(job_id)
        if not job:
            return {"error": f"Job {job_id} not found"}

        ctx = self._job_contexts.get(job_id)
        return {
            "job_id": job_id,
            "session_id": job.session_id,
            "status": job.status.value,
            "kind": job.kind.value,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "is_paused": ctx.is_paused if ctx else False,
            "is_cancelled": ctx.is_cancelled if ctx else False,
            "error": job.error,
            "metadata": dict(job.metadata),
        }

    def get_job_event_head_sequence(self, job_id: str) -> int:
        """Return the highest event sequence currently recorded for a job.

        Args:
            job_id: Runtime job identifier.

        Returns:
            The highest per-job sequence, or ``0`` when the job has no events.

        Raises:
            ValueError: If ``job_id`` is blank.
        """
        normalized = str(job_id or "").strip()
        if not normalized:
            raise ValueError("job_id must not be empty")
        job = self.get_job(normalized)
        if job is None:
            return 0
        self._ensure_session_event_sequences(job.session_id)
        return max(
            (event.sequence for event in self._events.get(job.session_id, []) if event.job_id == normalized),
            default=0,
        )

    @staticmethod
    def _coerce_event_sequence(value: Any) -> int:
        """Coerce persisted sequence values into the safe non-negative range."""
        if isinstance(value, bool):
            return 0
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return parsed if parsed > 0 else 0

    def _next_event_sequence(self, job_id: str) -> int:
        """Return the next monotonic sequence value for one job."""
        normalized = str(job_id or "").strip()
        if not normalized:
            raise ValueError("job_id must not be empty")
        highest = 0
        for events in self._events.values():
            for event in events:
                if event.job_id == normalized and event.sequence > highest:
                    highest = event.sequence
        return highest + 1

    def _with_event_sequence(self, event: WritingEvent) -> WritingEvent:
        """Attach a per-job sequence when an incoming event does not have one."""
        if event.sequence > 0:
            return event
        return replace(event, sequence=self._next_event_sequence(event.job_id))

    def _ensure_session_event_sequences(self, session_id: str) -> None:
        """Backfill missing event sequences for old in-memory or persisted state."""
        events = self._events.get(session_id, [])
        if not events:
            return
        next_by_job: dict[str, int] = {}
        for event in events:
            current_sequence = self._coerce_event_sequence(event.sequence)
            if current_sequence > 0:
                next_by_job[event.job_id] = max(next_by_job.get(event.job_id, 1), current_sequence + 1)
        normalized_events: list[WritingEvent] = []
        changed = False
        for event in sorted(events, key=lambda item: (item.timestamp, item.event_id)):
            job_id = event.job_id
            current_sequence = self._coerce_event_sequence(event.sequence)
            if current_sequence > 0:
                normalized_events.append(event if current_sequence == event.sequence else replace(event, sequence=current_sequence))
                changed = changed or current_sequence != event.sequence
                continue
            next_sequence = next_by_job.get(job_id, 1)
            next_by_job[job_id] = next_sequence + 1
            normalized_events.append(replace(event, sequence=next_sequence))
            changed = True
        if changed:
            self._events[session_id] = normalized_events

    def emit_job_progress(
        self,
        job_id: str,
        *,
        stage: str,
        message: str,
        progress: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Append a machine-readable progress event for a running job.

        Args:
            job_id: Existing runtime job identifier.
            stage: Stable stage key, short ASCII or Chinese label.
            message: User-facing progress summary.
            progress: Optional 0..100 progress percentage.
            data: Optional JSON-serializable event payload extensions.

        Raises:
            ValueError: If the job does not exist or payload fields are blank.
        """
        normalized_stage = str(stage or "").strip()
        normalized_message = str(message or "").strip()
        if not normalized_stage:
            raise ValueError("stage must not be empty")
        if not normalized_message:
            raise ValueError("message must not be empty")
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        payload: dict[str, Any] = {
            "stage": normalized_stage,
            "message": normalized_message,
        }
        if progress is not None:
            payload["progress"] = max(0, min(100, int(progress)))
        if data:
            payload.update(dict(data))
        metadata = dict(job.metadata)
        metadata.update(
            {
                "progress_stage": normalized_stage,
                "progress_message": normalized_message,
                **({"progress": payload["progress"]} if "progress" in payload else {}),
            }
        )
        self._jobs[job_id] = replace(job, metadata=metadata)
        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_PROGRESS,
                data=payload,
            ),
        )
        self._autosave_if_enabled()

    # ==========================================================================
    # Job Lifecycle Control
    # ==========================================================================

    async def start_job(self, job_id: str, executor: Callable[[WritingJob], Any] | None = None) -> WritingJob:
        """
        Start executing a job.
        
        If executor is provided, it will be called asynchronously.
        The executor should handle pause/resume/cancel via the context.
        """
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Transition to STARTED
        job = job.with_status(JobStatus.STARTED)
        self._jobs[job_id] = job

        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_STARTED,
            ),
        )

        self._logger.info("Started job %s", job_id)

        if executor:
            task = asyncio.create_task(self._run_job_executor(job_id, executor))
            self._job_tasks[job_id] = task

        self._autosave_if_enabled()
        return self.get_job(job_id) or job

    async def _run_job_executor(self, job_id: str, executor: Callable[[WritingJob], Any]) -> None:
        """Run a job executor outside the request path and finalize its result."""
        job = self.get_job(job_id)
        if not job:
            self._job_tasks.pop(job_id, None)
            return
        try:
            ctx = self._job_contexts.get(job_id)
            if ctx and ctx.is_cancelled:
                return
            job = job.with_status(JobStatus.IN_PROGRESS)
            self._jobs[job_id] = job
            self._emit_event(
                job.session_id,
                WritingEvent.create(
                    job_id=job_id,
                    session_id=job.session_id,
                    event_type=EventType.JOB_PROGRESS,
                    data={"stage": "running", "message": "任务已进入后台执行"},
                ),
            )
            executor_result = executor(job)
            if inspect.isawaitable(executor_result):
                executor_result = await executor_result
            ctx = self._job_contexts.get(job_id)
            current = self.get_job(job_id)
            if (ctx and ctx.is_cancelled) or (current and current.status == JobStatus.CANCELLED):
                return
            await self._finalize_executor_result(job_id, executor_result)
        except asyncio.CancelledError:
            current = self.get_job(job_id)
            if current and current.status != JobStatus.CANCELLED:
                await self.cancel_job(job_id)
            raise
        except _RUNTIME_RECOVERABLE_EXCEPTIONS as exc:
            current = self.get_job(job_id)
            if current and current.status != JobStatus.CANCELLED:
                self._logger.error("Executor error for job %s: %s", job_id, exc)
                await self.fail_job(job_id, str(exc))
        except BaseException as exc:  # noqa: BLE001 — must not silently drop FastAPI HTTPException; UI relies on JOB_FAILED event.
            # HTTPException (FastAPI/Starlette) inherits from Exception, not the
            # narrow recoverable tuple above. Without this branch, a 400/401
            # from chat/embedding/rerank providers escapes asyncio as
            # "Task exception was never retrieved" and the job stays
            # IN_PROGRESS forever — the UI calls this "stuck at 1800s".
            if _is_http_like_exception(exc):
                current = self.get_job(job_id)
                if current and current.status != JobStatus.CANCELLED:
                    msg = _format_http_exception(exc)
                    self._logger.error("HTTP error for job %s: %s", job_id, msg)
                    await self.fail_job(job_id, msg)
                return  # swallow — fail_job already emitted JOB_FAILED
            raise  # truly unknown error: surface to asyncio, don't lie
        finally:
            self._job_tasks.pop(job_id, None)
            self._autosave_if_enabled()

    async def pause_job(self, job_id: str) -> WritingJob:
        """Pause a running job."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job.status not in (JobStatus.STARTED, JobStatus.IN_PROGRESS):
            raise ValueError(f"Cannot pause job in status {job.status.value}")

        ctx = self._job_contexts.get(job_id)
        if ctx:
            ctx.is_paused = True
            ctx.pause_event.clear()

        job = job.with_status(JobStatus.PAUSED)
        self._jobs[job_id] = job

        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_PAUSED,
            ),
        )

        self._logger.info("Paused job %s", job_id)
        self._autosave_if_enabled()
        return job

    async def resume_job(self, job_id: str) -> WritingJob:
        """Resume a paused job."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job.status != JobStatus.PAUSED:
            raise ValueError(f"Cannot resume job in status {job.status.value}")

        ctx = self._job_contexts.get(job_id)
        if ctx:
            ctx.is_paused = False
            ctx.pause_event.set()

        job = job.with_status(JobStatus.IN_PROGRESS)
        self._jobs[job_id] = job

        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_RESUMED,
            ),
        )

        self._logger.info("Resumed job %s", job_id)
        self._autosave_if_enabled()
        return job

    async def cancel_job(self, job_id: str) -> WritingJob:
        """Cancel a job."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            raise ValueError(f"Cannot cancel job already in terminal status {job.status.value}")

        ctx = self._job_contexts.get(job_id)
        if ctx:
            ctx.is_cancelled = True
            ctx.cancel_event.set()
        task = self._job_tasks.pop(job_id, None)
        if task is not None and not task.done():
            task.cancel()

        job = job.with_status(JobStatus.CANCELLED)
        self._jobs[job_id] = job

        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_CANCELLED,
            ),
        )

        self._logger.info("Cancelled job %s", job_id)
        self._create_checkpoint(job.session_id, kind="job_cancelled", source_job_id=job_id)
        self._autosave_if_enabled()
        return job

    async def complete_job(self, job_id: str, result: Any | None = None) -> WritingJob:
        """Mark a job as completed."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        job = job.with_status(JobStatus.COMPLETED)
        self._jobs[job_id] = job

        if result:
            self._store_artifact(
                WritingArtifact.create(
                    job_id=job_id,
                    session_id=job.session_id,
                    artifact_type=ArtifactType.TRANSFORMED_TEXT,
                    content=result,
                    created_by="system",
                )
            )

        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_COMPLETED,
                data={"result_artifact_count": len(self._artifacts.get(job_id, []))},
            ),
        )

        self._sync_job_to_memory_if_enabled(job_id)
        self._schedule_runtime_job_capture(job)
        self._create_checkpoint(job.session_id, kind="job_completed", source_job_id=job_id)
        self._logger.info("Completed job %s", job_id)
        self._autosave_if_enabled()
        return job

    async def fail_job(self, job_id: str, error: str) -> WritingJob:
        """Mark a job as failed with error message."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        job = job.with_error(error)
        self._jobs[job_id] = job

        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_FAILED,
                data={"error": error},
            ),
        )

        self._sync_job_to_memory_if_enabled(job_id)
        self._schedule_runtime_job_capture(job, error=error)
        self._create_checkpoint(job.session_id, kind="job_failed", source_job_id=job_id)
        self._logger.info("Failed job %s: %s", job_id, error)
        self._autosave_if_enabled()
        return job

    def _schedule_runtime_job_capture(
        self,
        job: "WritingJob",
        *,
        error: str | None = None,
    ) -> None:
        """Fire runtime-job capture off the terminal-state path."""

        try:
            from evolution import run_capture_in_background
        except Exception as exc:  # pragma: no cover - evolution package missing
            self._logger.debug(
                "evolution package unavailable; runtime capture skipped: %s", exc
            )
            return
        run_capture_in_background(
            self._capture_runtime_job_to_evolution,
            job,
            label="runtime",
            error=error,
        )

    def _capture_runtime_job_to_evolution(
        self,
        job: "WritingJob",
        *,
        error: str | None = None,
    ) -> None:
        """Best-effort runtime-job → evolution candidate write.

        Capture contract:
          - never raises; capture failures degrade to a debug log
          - skipped entirely when evolution.candidate_capture_enabled = false
          - CANCELLED jobs are not captured (extractor returns None)
          - existing complete_job / fail_job behavior unchanged otherwise
        """

        try:
            from evolution import (
                extract_from_job,
                get_evolution_service,
                is_candidate_capture_enabled,
            )
        except Exception as exc:  # pragma: no cover - evolution package missing
            self._logger.debug("evolution package unavailable; runtime capture skipped: %s", exc)
            return

        if not is_candidate_capture_enabled():
            return

        try:
            args = extract_from_job(job, error=error)
        except Exception as exc:
            self._logger.warning("runtime capture extractor failed: %s", exc)
            return
        if args is None:
            return

        try:
            service = get_evolution_service()
            service.capture(
                workspace_id=args.workspace_id,
                source_type=args.source_type,
                source_id=args.source_id,
                source_summary=args.source_summary,
                memory_type=args.memory_type,
                title=args.title,
                claim=args.claim,
                future_use=args.future_use,
                confidence=args.confidence,
                project_id=args.project_id,
                source_route=args.source_route,
                evidence_refs=args.evidence_refs,
                risk_level=args.risk_level,
            )
        except Exception as exc:
            self._logger.warning(
                "runtime capture write failed for job %s: %s", job.job_id, exc,
            )

    def _schedule_skill_capture(
        self,
        job: "WritingJob",
        result: "SkillRunResult",
    ) -> None:
        """Fire skill capture off the job-completion path."""

        try:
            from evolution import run_capture_in_background
        except Exception as exc:  # pragma: no cover - evolution package missing
            self._logger.debug(
                "evolution package unavailable; skill capture skipped: %s", exc
            )
            return
        run_capture_in_background(
            self._capture_skill_run_to_evolution, job, result, label="skill"
        )

    def _capture_skill_run_to_evolution(
        self,
        job: "WritingJob",
        result: "SkillRunResult",
    ) -> None:
        """Best-effort skill_run → evolution candidate write.

        Capture contract:
          - never raises; capture failures degrade to a warning log
          - skipped entirely when evolution.candidate_capture_enabled = false
          - SUCCESS / PARTIAL  → SKILL_DRAFT candidate (future promotion may
                                  promote to a managed disabled skill draft)
          - FAILED / TIMEOUT / CANCELLED → TOOL_RELIABILITY candidate
          - both candidates coexist with the broader runtime-job capture
            (different source_type so they never dedupe; reviewers see both)
        """

        try:
            from evolution import (
                extract_from_skill_run,
                get_evolution_service,
                is_candidate_capture_enabled,
            )
        except Exception as exc:  # pragma: no cover - evolution package missing
            self._logger.debug("evolution package unavailable; skill capture skipped: %s", exc)
            return

        if not is_candidate_capture_enabled():
            return

        try:
            args = extract_from_skill_run(result, job=job)
        except Exception as exc:
            self._logger.warning("skill capture extractor failed: %s", exc)
            return
        if args is None:
            return

        try:
            service = get_evolution_service()
            service.capture(
                workspace_id=args.workspace_id,
                source_type=args.source_type,
                source_id=args.source_id,
                source_summary=args.source_summary,
                memory_type=args.memory_type,
                title=args.title,
                claim=args.claim,
                future_use=args.future_use,
                confidence=args.confidence,
                project_id=args.project_id,
                source_route=args.source_route,
                evidence_refs=args.evidence_refs,
                risk_level=args.risk_level,
            )
        except Exception as exc:
            self._logger.warning(
                "skill capture write failed for job %s skill %s: %s",
                job.job_id, getattr(result, "skill_id", "?"), exc,
            )

    def _normalize_skill_run_result(self, job: WritingJob, result: SkillRunResult) -> SkillRunResult:
        """Rewrite skill results so the runtime job ID stays authoritative."""
        if result.job_id == job.job_id:
            return result

        metadata = dict(result.metadata)
        metadata.setdefault("source_skill_job_id", result.job_id)

        return SkillRunResult(
            job_id=job.job_id,
            skill_id=result.skill_id,
            status=result.status,
            input_text=result.input_text,
            output_text=result.output_text,
            timestamp=result.timestamp,
            execution_time_ms=result.execution_time_ms,
            warnings=list(result.warnings),
            metadata=metadata,
            structured_output=dict(result.structured_output),
            evidence_refs=list(result.evidence_refs),
            audit_id=result.audit_id,
        )

    def _store_skill_run_artifact(self, job: WritingJob, result: SkillRunResult) -> WritingArtifact:
        """Persist a skill result as a typed artifact."""
        artifact_type = ArtifactType.AUDIT_RECORD if result.is_failed() else ArtifactType.TRANSFORMED_TEXT
        artifact = WritingArtifact.create(
            job_id=job.job_id,
            session_id=job.session_id,
            artifact_type=artifact_type,
            content=result.to_dict(),
            created_by=result.skill_id,
            metadata={
                "execution_time_ms": result.execution_time_ms,
                "warnings": list(result.warnings),
                "skill_result_status": result.status.value,
                "source_skill_job_id": result.job_id,
                **dict(result.metadata),
            },
            mime_type="application/json",
        )
        self._store_artifact(artifact)
        return artifact

    async def _finalize_executor_result(self, job_id: str, executor_result: Any) -> WritingJob | None:
        """Finalize a job when an executor returns a concrete result."""
        job = self.get_job(job_id)
        if not job:
            return None

        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return job

        if isinstance(executor_result, SkillRunResult):
            normalized_result = self._normalize_skill_run_result(job, executor_result)
            self._store_skill_run_artifact(job, normalized_result)
            self._schedule_skill_capture(job, normalized_result)

            if normalized_result.is_failed():
                error_message = (
                    normalized_result.output_text
                    or "; ".join(normalized_result.warnings)
                    or f"Skill execution failed: {normalized_result.status.value}"
                )
                await self.fail_job(job_id, error_message)
            else:
                await self.complete_job(job_id)
            return self.get_job(job_id)

        if isinstance(executor_result, dict):
            status_value = str(executor_result.get("status", "")).lower()
            if status_value in {"failed", "timeout", "cancelled"} or "error" in executor_result:
                error_message = str(
                    executor_result.get("error")
                    or executor_result.get("message")
                    or executor_result.get("output_text")
                    or executor_result
                )
                await self.fail_job(job_id, error_message)
            else:
                await self.complete_job(job_id, result=executor_result)
            return self.get_job(job_id)

        if isinstance(executor_result, str):
            await self.complete_job(job_id, result=executor_result)
            return self.get_job(job_id)

        return job

    def sync_job_to_memory(
        self,
        job_id: str,
        wing: str | None = None,
        room: str | None = None,
    ) -> dict[str, Any]:
        """
        Persist a terminal job into MemPalace when the adapter is available.

        Why:
            Long-term memory should never block job lifecycle transitions. This
            method isolates the sync step behind a best-effort adapter boundary.
        """
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        adapter = self._get_memory_adapter()
        if adapter is None:
            return {
                "success": False,
                "available": False,
                "reason": "mempalace adapter unavailable",
                "wing": wing or "",
                "room": room or "",
            }

        session = self.get_session(job.session_id)
        artifacts = self.get_job_artifacts(job_id)
        events = self.get_job_events(job_id)
        result = adapter.sync_runtime_job(
            job,
            session,
            artifacts,
            events,
            wing=wing,
            room=room,
        )
        if hasattr(result, "to_dict"):
            return result.to_dict()
        if isinstance(result, dict):
            return result
        return {
            "success": False,
            "available": False,
            "reason": "unexpected mempalace sync response",
            "wing": wing or "",
            "room": room or "",
        }

    # ==========================================================================
    # Event Management
    # ==========================================================================

    def get_job_events(
        self,
        job_id: str,
        since_timestamp: str | None = None,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int | None = None,
    ) -> list[WritingEvent]:
        """Get events for a job, optionally filtered by a polling cursor."""
        job = self.get_job(job_id)
        if not job:
            return []

        session_id = job.session_id
        if after_sequence is not None and after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        self._ensure_session_event_sequences(session_id)
        session_events = self._events.get(session_id, [])
        job_events = sorted(
            [e for e in session_events if e.job_id == job_id],
            key=lambda event: (event.sequence, event.timestamp, event.event_id),
        )

        if after_sequence is not None:
            job_events = [event for event in job_events if event.sequence > after_sequence]
        elif since_timestamp is not None:
            job_events = [
                event
                for event in job_events
                if event.timestamp > since_timestamp
                or (
                    event.timestamp == since_timestamp
                    and after_event_id is not None
                    and event.event_id > after_event_id
                )
            ]
        elif after_event_id is not None:
            cursor_index = next(
                (
                    index
                    for index, event in enumerate(job_events)
                    if event.event_id == after_event_id
                ),
                None,
            )
            if cursor_index is not None:
                job_events = job_events[cursor_index + 1 :]

        if limit is not None:
            job_events = job_events[:limit]

        return job_events

    def subscribe_to_events(self, session_id: str, callback: Callable[[WritingEvent], None]) -> None:
        """Subscribe to events in a session."""
        if session_id not in self._event_subscribers:
            self._event_subscribers[session_id] = []
        self._event_subscribers[session_id].append(callback)

    def _emit_event(self, session_id: str, event: WritingEvent) -> None:
        """Emit an event to all subscribers."""
        if session_id not in self._events:
            self._events[session_id] = []
        sequenced_event = self._with_event_sequence(event)
        self._events[session_id].append(sequenced_event)
        event_payload = sequenced_event.to_dict()
        event_payload.update(dict(event.data))
        self._append_transcript_event(session_id, event.event_type.value, event_payload)

        # Notify subscribers
        subscribers = self._event_subscribers.get(session_id, [])
        for callback in subscribers:
            try:
                callback(sequenced_event)
            except _RUNTIME_RECOVERABLE_EXCEPTIONS as exc:
                self._logger.error("Error in event subscriber: %s", exc)

    # ==========================================================================
    # Artifact Management
    # ==========================================================================

    def get_job_artifacts(self, job_id: str, artifact_type: ArtifactType | None = None) -> list[WritingArtifact]:
        """Get artifacts for a job, optionally filtered by type."""
        artifacts = self._artifacts.get(job_id, [])
        if artifact_type:
            artifacts = [a for a in artifacts if a.artifact_type == artifact_type]
        return artifacts

    def _store_artifact(self, artifact: WritingArtifact) -> None:
        """Store an artifact (internal method)."""
        if artifact.job_id not in self._artifacts:
            self._artifacts[artifact.job_id] = []
        self._artifacts[artifact.job_id].append(artifact)
        self._append_transcript_event(artifact.session_id, "artifact_created", artifact.to_dict())

    # ==========================================================================
    # Approval Management
    # ==========================================================================

    def request_approval(
        self,
        job_id: str,
        session_id: str,
        reason: str,
        content_preview: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WritingApprovalRequest:
        """Request user approval for a job."""
        approval = WritingApprovalRequest.create(
            job_id=job_id,
            session_id=session_id,
            reason=reason,
            content_preview=content_preview,
            metadata=metadata,
        )
        self._approval_requests[approval.approval_id] = approval

        self._emit_event(
            session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=session_id,
                event_type=EventType.APPROVAL_REQUIRED,
                data={"approval_id": approval.approval_id, "reason": reason},
            ),
        )

        self._logger.info("Created approval request %s for job %s", approval.approval_id, job_id)
        self._autosave_if_enabled()
        return approval

    def get_approval_request(self, approval_id: str) -> WritingApprovalRequest | None:
        """Get an approval request by ID."""
        return self._approval_requests.get(approval_id)

    async def grant_approval(self, approval_id: str, response_by: str | None = None) -> WritingApprovalRequest:
        """Grant approval."""
        approval = self.get_approval_request(approval_id)
        if not approval:
            raise ValueError(f"Approval request {approval_id} not found")

        if approval.status != ApprovalStatus.PENDING:
            raise ValueError(f"Cannot grant approval already in status {approval.status.value}")

        approval = approval.with_approval(response_by=response_by)
        self._approval_requests[approval_id] = approval

        self._emit_event(
            approval.session_id,
            WritingEvent.create(
                job_id=approval.job_id,
                session_id=approval.session_id,
                event_type=EventType.APPROVAL_GRANTED,
                data={"approval_id": approval_id},
            ),
        )

        self._logger.info("Granted approval %s", approval_id)
        self._autosave_if_enabled()
        return approval

    async def reject_approval(self, approval_id: str, response_by: str | None = None) -> WritingApprovalRequest:
        """Reject approval."""
        approval = self.get_approval_request(approval_id)
        if not approval:
            raise ValueError(f"Approval request {approval_id} not found")

        if approval.status != ApprovalStatus.PENDING:
            raise ValueError(f"Cannot reject approval already in status {approval.status.value}")

        approval = approval.with_rejection(response_by=response_by)
        self._approval_requests[approval_id] = approval

        self._emit_event(
            approval.session_id,
            WritingEvent.create(
                job_id=approval.job_id,
                session_id=approval.session_id,
                event_type=EventType.APPROVAL_REJECTED,
                data={"approval_id": approval_id},
            ),
        )

        self._logger.info("Rejected approval %s", approval_id)
        self._autosave_if_enabled()
        return approval

    # ==========================================================================
    # Backward Compatibility - Legacy Action Execution
    # ==========================================================================

    async def execute_action(
        self,
        session_id: str,
        action_id: str,
        input_text: str,
        scope: str = "section",
        output_mode: str = "word_safe",
        executor: Callable[[WritingJob], Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute a legacy action through the runtime.
        
        Creates a job, executes it, and returns compatibility-formatted result.
        Maintains backward compatibility with existing action execution flows.
        """
        job = self.create_job(
            session_id=session_id,
            kind=JobKind.PROMPT_ACTION,
            input_text=input_text,
            action_id=action_id,
            scope=scope,
            output_mode=output_mode,
            tags=["legacy_action"],
        )

        await self.start_job(job.job_id, executor=executor)

        final_job = self.get_job(job.job_id) or job
        if final_job.status not in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            await self.complete_job(job.job_id)
            final_job = self.get_job(job.job_id) or final_job

        artifacts = self.get_job_artifacts(job.job_id)
        output_text = ""
        if artifacts:
            first_artifact = artifacts[0]
            if isinstance(first_artifact.content, str):
                output_text = first_artifact.content
            elif isinstance(first_artifact.content, dict):
                output_text = (
                    first_artifact.content.get("output_text")
                    or first_artifact.content.get("error")
                    or first_artifact.content.get("text")
                    or str(first_artifact.content)
                )

        if not output_text and final_job.error:
            output_text = final_job.error

        status_value = final_job.status.value
        if final_job.status == JobStatus.COMPLETED:
            status_value = "succeeded"

        return {
            "job_id": job.job_id,
            "status": status_value,
            "input": input_text,
            "output": output_text,
            "action_id": action_id,
            **({"error": final_job.error} if final_job.status != JobStatus.COMPLETED and final_job.error else {}),
        }

    # ==========================================================================
    # State Export (for debugging and persistence preparation)
    # ==========================================================================

    def export_state(self) -> dict[str, Any]:
        """Export full runtime state (for snapshots and persistence)."""
        return {
            "sessions": {sid: s.to_dict() for sid, s in self._sessions.items()},
            "jobs": {jid: j.to_dict() for jid, j in self._jobs.items()},
            "job_queue": self._job_queue[:],
            "events": {
                sid: [e.to_dict() for e in events]
                for sid, events in self._events.items()
            },
            "artifacts": {
                jid: [a.to_dict() for a in artifacts]
                for jid, artifacts in self._artifacts.items()
            },
            "approval_requests": {
                aid: a.to_dict() for aid, a in self._approval_requests.items()
            },
            "checkpoints": {
                sid: [dict(checkpoint) for checkpoint in checkpoints]
                for sid, checkpoints in self._session_checkpoints.items()
            },
        }

    def import_state(self, state: dict[str, Any]) -> None:
        """Import runtime state (for recovery and restoration)."""
        if not isinstance(state, dict):
            raise TypeError("state must be a dictionary")

        sessions_raw = state.get("sessions", {})
        jobs_raw = state.get("jobs", {})
        job_queue_raw = state.get("job_queue", [])
        events_raw = state.get("events", {})
        artifacts_raw = state.get("artifacts", {})
        approvals_raw = state.get("approval_requests", state.get("approvals", {}))
        checkpoints_raw = state.get("checkpoints", {})

        if not isinstance(sessions_raw, dict):
            raise TypeError("sessions must be a mapping")
        if not isinstance(jobs_raw, dict):
            raise TypeError("jobs must be a mapping")
        if not isinstance(events_raw, dict):
            raise TypeError("events must be a mapping")
        if not isinstance(artifacts_raw, dict):
            raise TypeError("artifacts must be a mapping")
        if not isinstance(approvals_raw, dict):
            raise TypeError("approval_requests must be a mapping")
        if not isinstance(checkpoints_raw, dict):
            raise TypeError("checkpoints must be a mapping")
        if not isinstance(job_queue_raw, list):
            raise TypeError("job_queue must be a list")

        sessions: dict[str, WritingSession] = {}
        for session_id, payload in sessions_raw.items():
            if not isinstance(payload, dict):
                raise TypeError("session payload must be a mapping")
            session = WritingSession(
                session_id=str(payload["session_id"]),
                user_id=None if payload.get("user_id") in (None, "") else str(payload.get("user_id")),
                mode=SessionMode(str(payload.get("mode", SessionMode.PROMPT.value))),
                created_at=str(payload.get("created_at")),
                settings=dict(payload.get("settings") or {}),
                tags=[str(tag) for tag in payload.get("tags", [])],
                metadata=dict(payload.get("metadata") or {}),
            )
            sessions[str(session_id)] = session

        jobs: dict[str, WritingJob] = {}
        for job_id, payload in jobs_raw.items():
            if not isinstance(payload, dict):
                raise TypeError("job payload must be a mapping")
            job = WritingJob(
                job_id=str(payload["job_id"]),
                session_id=str(payload["session_id"]),
                kind=JobKind(str(payload.get("kind", JobKind.PROMPT_ACTION.value))),
                status=JobStatus(str(payload.get("status", JobStatus.CREATED.value))),
                input_text=str(payload.get("input_text", "")),
                created_at=str(payload.get("created_at")),
                started_at=payload.get("started_at"),
                completed_at=payload.get("completed_at"),
                action_id=None if payload.get("action_id") in (None, "") else str(payload.get("action_id")),
                skill_id=None if payload.get("skill_id") in (None, "") else str(payload.get("skill_id")),
                scope=None if payload.get("scope") in (None, "") else str(payload.get("scope")),
                output_mode=None if payload.get("output_mode") in (None, "") else str(payload.get("output_mode")),
                error=None if payload.get("error") in (None, "") else str(payload.get("error")),
                tags=[str(tag) for tag in payload.get("tags", [])],
                metadata=dict(payload.get("metadata") or {}),
            )
            jobs[str(job_id)] = job

        self._sessions = sessions
        self._jobs = jobs
        self._job_queue = [str(job_id) for job_id in job_queue_raw if str(job_id) in jobs]
        if not self._job_queue:
            self._job_queue = list(jobs.keys())

        self._job_contexts = {}
        for job_id, job in jobs.items():
            ctx = JobExecutionContext(job=job)
            if job.status == JobStatus.PAUSED:
                ctx.is_paused = True
                ctx.pause_event.clear()
            if job.status == JobStatus.CANCELLED:
                ctx.is_cancelled = True
                ctx.cancel_event.set()
            self._job_contexts[job_id] = ctx
        self._job_tasks = {}

        events: dict[str, list[WritingEvent]] = {}
        for session_id, event_list in events_raw.items():
            if not isinstance(event_list, list):
                raise TypeError("event lists must be lists")
            restored_events: list[WritingEvent] = []
            for event_payload in event_list:
                if not isinstance(event_payload, dict):
                    raise TypeError("event payload must be a mapping")
                restored_events.append(
                    WritingEvent(
                        event_id=str(event_payload["event_id"]),
                        job_id=str(event_payload["job_id"]),
                        session_id=str(event_payload["session_id"]),
                        event_type=EventType(str(event_payload.get("event_type", EventType.JOB_CREATED.value))),
                        timestamp=str(event_payload.get("timestamp")),
                        sequence=self._coerce_event_sequence(event_payload.get("sequence")),
                        data=dict(event_payload.get("data") or {}),
                        metadata=dict(event_payload.get("metadata") or {}),
                    )
                )
            events[str(session_id)] = restored_events
        self._events = events
        for session_id in list(self._events.keys()):
            self._ensure_session_event_sequences(session_id)

        artifacts: dict[str, list[WritingArtifact]] = {}
        for job_id, artifact_list in artifacts_raw.items():
            if not isinstance(artifact_list, list):
                raise TypeError("artifact lists must be lists")
            restored_artifacts: list[WritingArtifact] = []
            for artifact_payload in artifact_list:
                if not isinstance(artifact_payload, dict):
                    raise TypeError("artifact payload must be a mapping")
                restored_artifacts.append(
                    WritingArtifact(
                        artifact_id=str(artifact_payload["artifact_id"]),
                        job_id=str(artifact_payload["job_id"]),
                        session_id=str(artifact_payload["session_id"]),
                        artifact_type=ArtifactType(str(artifact_payload.get("artifact_type", ArtifactType.METADATA.value))),
                        content=artifact_payload.get("content"),
                        created_at=str(artifact_payload.get("created_at")),
                        created_by=None if artifact_payload.get("created_by") in (None, "") else str(artifact_payload.get("created_by")),
                        metadata=dict(artifact_payload.get("metadata") or {}),
                        mime_type=str(artifact_payload.get("mime_type", "application/json")),
                    )
                )
            artifacts[str(job_id)] = restored_artifacts
        self._artifacts = artifacts

        approvals: dict[str, WritingApprovalRequest] = {}
        for approval_id, payload in approvals_raw.items():
            if not isinstance(payload, dict):
                raise TypeError("approval payload must be a mapping")
            approvals[str(approval_id)] = WritingApprovalRequest(
                approval_id=str(payload["approval_id"]),
                job_id=str(payload["job_id"]),
                session_id=str(payload["session_id"]),
                status=ApprovalStatus(str(payload.get("status", ApprovalStatus.PENDING.value))),
                requested_at=str(payload.get("requested_at")),
                reason=str(payload.get("reason", "")),
                content_preview=None if payload.get("content_preview") in (None, "") else str(payload.get("content_preview")),
                response_by=None if payload.get("response_by") in (None, "") else str(payload.get("response_by")),
                responded_at=None if payload.get("responded_at") in (None, "") else str(payload.get("responded_at")),
                metadata=dict(payload.get("metadata") or {}),
            )
        self._approval_requests = approvals
        checkpoints: dict[str, list[dict[str, Any]]] = {}
        for session_id, checkpoint_list in checkpoints_raw.items():
            if not isinstance(checkpoint_list, list):
                raise TypeError("checkpoint lists must be lists")
            restored_checkpoints: list[dict[str, Any]] = []
            for checkpoint_payload in checkpoint_list:
                if not isinstance(checkpoint_payload, dict):
                    raise TypeError("checkpoint payload must be a mapping")
                restored_checkpoints.append(
                    {
                        "checkpoint_id": str(checkpoint_payload["checkpoint_id"]),
                        "session_id": str(checkpoint_payload["session_id"]),
                        "event_id": str(checkpoint_payload["event_id"]),
                        "created_at": str(checkpoint_payload["created_at"]),
                        "kind": str(checkpoint_payload.get("kind", "auto")),
                        "metadata": dict(checkpoint_payload.get("metadata") or {}),
                    }
                )
            checkpoints[str(session_id)] = restored_checkpoints
        self._session_checkpoints = checkpoints
        self._session_transcripts = {session_id: [] for session_id in sessions.keys()}

        for session_id in sessions.keys():
            self._events.setdefault(session_id, [])
        for job_id in jobs.keys():
            self._artifacts.setdefault(job_id, [])
        self._logger.info("Imported runtime state with %s sessions and %s jobs", len(sessions), len(jobs))

    def persist_to_database(self) -> Path | None:
        """Persist the current runtime snapshot to SQLite."""
        if self._repository is None:
            return None

        self._repository.replace_state(self.export_state())
        return self._repository.db_path

    def load_from_database(self) -> bool:
        """Load runtime state from SQLite if the repository already has rows."""
        if self._repository is None:
            return False

        if not self._repository.is_healthy():
            self._logger.warning("Skipping SQLite runtime load because %s failed health checks", self._repository.db_path)
            return False

        if not self._repository.has_data():
            return False

        self.import_state(self._repository.load_state())
        self._hydrate_transcripts_from_repository()
        return True

    def _autosave_if_enabled(self) -> None:
        """Persist runtime state after mutating operations when autosave is enabled."""
        if self._autosave:
            self.persist_to_database()

    def _persist_state_after_event(self) -> None:
        """Persist the current state after an event or artifact mutation."""
        self._autosave_if_enabled()

    def _normalize_session_metadata(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        """Normalize workspace-bound session metadata for persistence and lookup."""
        payload = dict(metadata or {})
        explicit_root = payload.get("workspace_root")
        entry_cwd = Path(payload.get("entry_cwd") or explicit_root or Path.cwd()).expanduser().resolve()
        workspace_root = Path(explicit_root).expanduser().resolve() if explicit_root else _resolve_workspace_root(entry_cwd)
        payload["workspace_root"] = str(workspace_root)
        payload["entry_cwd"] = str(entry_cwd)
        payload["workspace_key"] = str(payload.get("workspace_key") or _stable_workspace_key(workspace_root))
        payload["title"] = str(payload.get("title") or "Untitled session")
        payload["status"] = str(payload.get("status") or "active")
        payload["updated_at"] = str(payload.get("updated_at") or utc_now_iso_z())
        payload.setdefault("head_event_id", None)
        payload.setdefault("head_checkpoint_id", None)
        payload.setdefault("parent_session_id", None)
        payload.setdefault("forked_from_turn_id", None)
        payload.setdefault("forked_from_checkpoint_id", None)
        return payload

    def _replace_session_metadata(self, session_id: str, **updates: Any) -> WritingSession:
        """Update a session metadata dict while preserving the immutable session object."""
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")
        metadata = dict(session.metadata)
        metadata.update(updates)
        updated_session = replace(session, metadata=metadata)
        self._sessions[session_id] = updated_session
        return updated_session

    def _refresh_session_title_from_first_prompt(self, session_id: str) -> None:
        """Replace placeholder titles with the first user-like transcript text."""
        session = self.get_session(session_id)
        if session is None:
            return
        current_title = str(session.metadata.get("title") or "").strip()
        if current_title and current_title.lower() != "untitled session":
            return
        first_prompt = ""
        for event in self._session_transcripts.get(session_id, []):
            payload = event.get("payload") if isinstance(event, dict) else None
            if not isinstance(payload, dict):
                continue
            if event.get("event_kind") not in {"job_created", "user", EventType.JOB_CREATED.value}:
                continue
            text = str(payload.get("input_text") or payload.get("text") or payload.get("content") or "").strip()
            if text:
                first_prompt = " ".join(text.split())[:30]
                break
        if first_prompt:
            self._replace_session_metadata(
                session_id,
                title=first_prompt,
                first_user_prompt=first_prompt,
            )

    def _append_transcript_event(
        self,
        session_id: str,
        event_kind: str,
        payload: dict[str, Any],
        *,
        parent_event_id: str | None = None,
        event_id: str | None = None,
        timestamp: str | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        """Append an event to the transcript and move the active session head."""
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")
        transcript_event = {
            "event_id": event_id or f"evt_{os.urandom(8).hex()}",
            "session_id": session_id,
            "event_kind": event_kind,
            "timestamp": timestamp or utc_now_iso_z(),
            "workspace_key": session.metadata["workspace_key"],
            "parent_event_id": parent_event_id if parent_event_id is not None else session.metadata.get("head_event_id"),
            "payload": payload,
        }
        self._session_transcripts.setdefault(session_id, []).append(transcript_event)
        self._replace_session_metadata(
            session_id,
            head_event_id=transcript_event["event_id"],
            updated_at=transcript_event["timestamp"],
        )
        if event_kind in {"job_created", "user"} or (
            event_kind == EventType.JOB_CREATED.value and any(
                str(payload.get(key) or "").strip()
                for key in ("input_text", "text", "content")
            )
        ):
            self._refresh_session_title_from_first_prompt(session_id)
        if persist and self._repository is not None:
            self._repository.append_transcript_event(session_id, transcript_event)
        return transcript_event

    def _create_checkpoint(
        self,
        session_id: str,
        *,
        kind: str,
        source_job_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a checkpoint marker at the current transcript head."""
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")
        anchor_event_id = session.metadata.get("head_event_id")
        checkpoint_id = f"chk_{os.urandom(8).hex()}"
        checkpoint_event = self._append_transcript_event(
            session_id,
            "checkpoint_created",
            {
                "checkpoint_id": checkpoint_id,
                "kind": kind,
                **({"source_job_id": source_job_id} if source_job_id else {}),
            },
            parent_event_id=anchor_event_id,
        )
        checkpoint = {
            "checkpoint_id": checkpoint_id,
            "session_id": session_id,
            "event_id": checkpoint_event["event_id"],
            "created_at": checkpoint_event["timestamp"],
            "kind": kind,
            "metadata": {
                "anchor_event_id": anchor_event_id,
                **({"source_job_id": source_job_id} if source_job_id else {}),
            },
        }
        self._session_checkpoints.setdefault(session_id, []).append(checkpoint)
        self._replace_session_metadata(session_id, head_checkpoint_id=checkpoint_id)
        return checkpoint

    def _ensure_transcript_loaded(self, session_id: str) -> None:
        """Load a transcript from disk when needed."""
        if self._session_transcripts.get(session_id):
            return
        if self._repository is None:
            return
        self._session_transcripts[session_id] = self._repository.load_transcript(session_id)

    def _get_lineage_to_event(self, session_id: str, event_id: str) -> list[dict[str, Any]]:
        """Follow parent pointers from an event back to the root."""
        self._ensure_transcript_loaded(session_id)
        event_index = {
            event["event_id"]: event
            for event in self._session_transcripts.get(session_id, [])
        }
        lineage: list[dict[str, Any]] = []
        current_event_id = event_id
        while current_event_id:
            event = event_index.get(current_event_id)
            if event is None:
                break
            lineage.append(event)
            current_event_id = event.get("parent_event_id")
        lineage.reverse()
        return lineage

    def _get_active_transcript(self, session_id: str) -> list[dict[str, Any]]:
        """Return the currently active transcript lineage."""
        session = self.get_session(session_id)
        if session is None:
            return []
        head_event_id = session.metadata.get("head_event_id")
        if not head_event_id:
            return []
        return self._get_lineage_to_event(session_id, head_event_id)

    def _get_checkpoint(self, session_id: str, checkpoint_id: str) -> dict[str, Any] | None:
        """Return a checkpoint record by ID for a session."""
        return next(
            (
                checkpoint
                for checkpoint in self._session_checkpoints.get(session_id, [])
                if checkpoint["checkpoint_id"] == checkpoint_id
            ),
            None,
        )

    def _hydrate_transcripts_from_repository(self) -> None:
        """Populate in-memory transcript caches after database rehydration."""
        if self._repository is None:
            return
        for session_id in self._sessions.keys():
            self._session_transcripts[session_id] = self._repository.load_transcript(session_id)

    def _get_memory_adapter(self) -> Any | None:
        """Resolve the optional MemPalace adapter lazily and cache the outcome."""
        if self._memory_adapter_resolved:
            return self._memory_adapter

        self._memory_adapter_resolved = True
        try:
            from layers.m_layer_mempalace_memory import (
                MempalaceMemoryAdapter,
                load_mempalace_settings,
            )

            self._memory_adapter = MempalaceMemoryAdapter(load_mempalace_settings())
        except _RUNTIME_RECOVERABLE_EXCEPTIONS as exc:  # pragma: no cover - optional integration path
            self._logger.warning("MemPalace adapter unavailable: %s", exc)
            self._memory_adapter = None
        return self._memory_adapter

    def _sync_job_to_memory_if_enabled(self, job_id: str) -> None:
        """Best-effort terminal job sync that never changes the job outcome."""
        adapter = self._get_memory_adapter()
        if adapter is None:
            return
        settings = getattr(adapter, "settings", None)
        if settings is None or not getattr(settings, "auto_sync_runtime_jobs", False):
            return

        try:
            sync_result = self.sync_job_to_memory(job_id)
        except _RUNTIME_RECOVERABLE_EXCEPTIONS as exc:  # pragma: no cover - defensive boundary
            self._logger.warning("MemPalace sync failed for job %s: %s", job_id, exc)
            return

        if sync_result.get("success"):
            if sync_result.get("duplicate"):
                self._logger.info(
                    "MemPalace sync skipped duplicate for job %s (%s/%s)",
                    job_id,
                    sync_result.get("wing", ""),
                    sync_result.get("room", ""),
                )
            else:
                self._logger.info(
                    "MemPalace sync stored job %s in %s/%s",
                    job_id,
                    sync_result.get("wing", ""),
                    sync_result.get("room", ""),
                )
            return

        reason = sync_result.get("reason")
        if sync_result.get("available", True):
            self._logger.warning("MemPalace sync did not complete for job %s: %s", job_id, reason)


@lru_cache(maxsize=1)
def _get_writing_runtime_singleton() -> WritingRuntime:
    return WritingRuntime(
        database_path=_default_runtime_db_path(),
        autosave=True,
    )


def get_writing_runtime() -> WritingRuntime:
    """Get or create the global WritingRuntime instance."""
    return _get_writing_runtime_singleton()
