# -*- coding: utf-8 -*-
"""SQLite repository for writing runtime state."""

from __future__ import annotations

from collections import defaultdict
import json
import os
from pathlib import Path
from typing import Any, Mapping

from db import (
    backup_sqlite_database,
    checkpoint_sqlite_wal,
    collect_sqlite_health_report,
    get_sqlite_database_stats,
    json_dumps,
    json_loads,
    open_sqlite_connection,
    restore_sqlite_database,
    vacuum_sqlite_database,
)


class WritingRuntimeRepository:
    """Durable SQLite storage for sessions, jobs, events, artifacts, approvals, and queue order."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser().resolve()
        self.storage_root = self.db_path.parent
        self.transcripts_dir = self.storage_root / "transcripts"
        self.blobs_dir = self.storage_root / "blobs"
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        conn = open_sqlite_connection(self.db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    mode TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    settings TEXT NOT NULL DEFAULT '{}',
                    tags TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_text TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    action_id TEXT,
                    skill_id TEXT,
                    scope TEXT,
                    output_mode TEXT,
                    error TEXT,
                    tags TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    data TEXT NOT NULL DEFAULT '{}',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    mime_type TEXT NOT NULL DEFAULT 'application/json',
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    content_preview TEXT,
                    response_by TEXT,
                    responded_at TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_session_id ON jobs(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_session_id ON events(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_job_id ON events(job_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_job_id ON artifacts(job_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_job_id ON approvals(job_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_session_id ON checkpoints(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_created_at ON checkpoints(created_at)")
            conn.commit()
        finally:
            conn.close()

    def has_data(self) -> bool:
        """Return True when the repository already contains runtime rows."""
        conn = open_sqlite_connection(self.db_path)
        try:
            row = conn.execute("SELECT 1 FROM sessions LIMIT 1").fetchone()
            return row is not None
        finally:
            conn.close()

    def get_health_report(self) -> dict[str, Any]:
        """Return a combined health report for the runtime database."""
        return collect_sqlite_health_report(self.db_path)

    def is_healthy(self) -> bool:
        """Return True when the runtime database passes integrity checks."""
        return bool(self.get_health_report()["ok"])

    def get_stats(self) -> dict[str, Any]:
        """Return low-level file and pragma statistics for the runtime database."""
        return get_sqlite_database_stats(self.db_path)

    def checkpoint_wal(self, mode: str = "PASSIVE") -> dict[str, Any]:
        """Checkpoint the runtime database WAL."""
        return checkpoint_sqlite_wal(self.db_path, mode=mode)

    def vacuum(self) -> dict[str, Any]:
        """Run VACUUM / optimize against the runtime database."""
        return vacuum_sqlite_database(self.db_path)

    def backup_to(self, backup_path: str | Path) -> Path:
        """Create a backup copy of the runtime database."""
        return backup_sqlite_database(self.db_path, backup_path)

    def restore_from(self, backup_path: str | Path) -> Path:
        """Restore the runtime database from a backup copy."""
        return restore_sqlite_database(backup_path, self.db_path)

    def replace_state(self, state: Mapping[str, Any]) -> None:
        """Replace the full runtime state from a serialized snapshot."""
        conn = open_sqlite_connection(self.db_path)
        try:
            conn.execute("BEGIN")
            for table in ("runtime_meta", "checkpoints", "approvals", "artifacts", "events", "jobs", "sessions"):
                conn.execute(f"DELETE FROM {table}")

            sessions = state.get("sessions", {})
            jobs = state.get("jobs", {})
            events = state.get("events", {})
            artifacts = state.get("artifacts", {})
            approvals = state.get("approval_requests", state.get("approvals", {}))
            checkpoints = state.get("checkpoints", {})
            job_queue = list(state.get("job_queue", []))

            conn.executemany(
                """
                INSERT INTO sessions (
                    session_id, user_id, mode, created_at, settings, tags, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(payload["session_id"]),
                        None if payload.get("user_id") in (None, "") else str(payload.get("user_id")),
                        str(payload.get("mode")),
                        str(payload.get("created_at")),
                        json_dumps(payload.get("settings") or {}),
                        json_dumps(list(payload.get("tags", []))),
                        json_dumps(payload.get("metadata") or {}),
                    )
                    for payload in sessions.values()
                ],
            )

            conn.executemany(
                """
                INSERT INTO jobs (
                    job_id, session_id, kind, status, input_text, created_at, started_at,
                    completed_at, action_id, skill_id, scope, output_mode, error, tags, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(payload["job_id"]),
                        str(payload["session_id"]),
                        str(payload.get("kind")),
                        str(payload.get("status")),
                        str(payload.get("input_text", "")),
                        str(payload.get("created_at")),
                        payload.get("started_at"),
                        payload.get("completed_at"),
                        payload.get("action_id"),
                        payload.get("skill_id"),
                        payload.get("scope"),
                        payload.get("output_mode"),
                        payload.get("error"),
                        json_dumps(list(payload.get("tags", []))),
                        json_dumps(payload.get("metadata") or {}),
                    )
                    for payload in jobs.values()
                ],
            )

            event_rows: list[tuple[str, str, str, str, str, str, str]] = []
            for _, event_list in events.items():
                if not isinstance(event_list, list):
                    raise TypeError("events entries must be lists")
                for event_payload in event_list:
                    event_rows.append(
                        (
                            str(event_payload["event_id"]),
                            str(event_payload["job_id"]),
                            str(event_payload["session_id"]),
                            str(event_payload.get("event_type")),
                            str(event_payload.get("timestamp")),
                            json_dumps(event_payload.get("data") or {}),
                            json_dumps(event_payload.get("metadata") or {}),
                        )
                    )
            conn.executemany(
                """
                INSERT INTO events (
                    event_id, job_id, session_id, event_type, timestamp, data, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                event_rows,
            )

            artifact_rows: list[tuple[str, str, str, str, str, str, str, str, str]] = []
            for _, artifact_list in artifacts.items():
                if not isinstance(artifact_list, list):
                    raise TypeError("artifacts entries must be lists")
                for artifact_payload in artifact_list:
                    artifact_rows.append(
                        (
                            str(artifact_payload["artifact_id"]),
                            str(artifact_payload["job_id"]),
                            str(artifact_payload["session_id"]),
                            str(artifact_payload.get("artifact_type")),
                            json_dumps(artifact_payload.get("content")),
                            str(artifact_payload.get("created_at")),
                            artifact_payload.get("created_by"),
                            json_dumps(artifact_payload.get("metadata") or {}),
                            str(artifact_payload.get("mime_type", "application/json")),
                        )
                    )
            conn.executemany(
                """
                INSERT INTO artifacts (
                    artifact_id, job_id, session_id, artifact_type, content, created_at,
                    created_by, metadata, mime_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                artifact_rows,
            )

            approval_rows = [
                (
                    str(payload["approval_id"]),
                    str(payload["job_id"]),
                    str(payload["session_id"]),
                    str(payload.get("status")),
                    str(payload.get("requested_at")),
                    str(payload.get("reason", "")),
                    payload.get("content_preview"),
                    payload.get("response_by"),
                    payload.get("responded_at"),
                    json_dumps(payload.get("metadata") or {}),
                )
                for payload in approvals.values()
            ]
            conn.executemany(
                """
                INSERT INTO approvals (
                    approval_id, job_id, session_id, status, requested_at, reason,
                    content_preview, response_by, responded_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                approval_rows,
            )

            checkpoint_rows: list[tuple[str, str, str, str, str, str]] = []
            for _, checkpoint_list in checkpoints.items():
                if not isinstance(checkpoint_list, list):
                    raise TypeError("checkpoints entries must be lists")
                for checkpoint_payload in checkpoint_list:
                    checkpoint_rows.append(
                        (
                            str(checkpoint_payload["checkpoint_id"]),
                            str(checkpoint_payload["session_id"]),
                            str(checkpoint_payload["event_id"]),
                            str(checkpoint_payload["created_at"]),
                            str(checkpoint_payload.get("kind", "auto")),
                            json_dumps(checkpoint_payload.get("metadata") or {}),
                        )
                    )
            conn.executemany(
                """
                INSERT INTO checkpoints (
                    checkpoint_id, session_id, event_id, created_at, kind, metadata
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                checkpoint_rows,
            )

            conn.execute(
                "INSERT OR REPLACE INTO runtime_meta (key, value) VALUES (?, ?)",
                ("job_queue", json_dumps(job_queue)),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def load_state(self) -> dict[str, Any]:
        """Load the runtime state as the same dictionary shape used by the runtime."""
        conn = open_sqlite_connection(self.db_path)
        try:
            sessions = {
                str(row["session_id"]): {
                    "session_id": row["session_id"],
                    "user_id": row["user_id"],
                    "mode": row["mode"],
                    "created_at": row["created_at"],
                    "settings": json_loads(row["settings"], default={}),
                    "tags": json_loads(row["tags"], default=[]),
                    "metadata": json_loads(row["metadata"], default={}),
                }
                for row in conn.execute("SELECT * FROM sessions ORDER BY created_at ASC, session_id ASC")
            }

            jobs = {
                str(row["job_id"]): {
                    "job_id": row["job_id"],
                    "session_id": row["session_id"],
                    "kind": row["kind"],
                    "status": row["status"],
                    "input_text": row["input_text"],
                    "created_at": row["created_at"],
                    "started_at": row["started_at"],
                    "completed_at": row["completed_at"],
                    "action_id": row["action_id"],
                    "skill_id": row["skill_id"],
                    "scope": row["scope"],
                    "output_mode": row["output_mode"],
                    "error": row["error"],
                    "tags": json_loads(row["tags"], default=[]),
                    "metadata": json_loads(row["metadata"], default={}),
                }
                for row in conn.execute("SELECT * FROM jobs ORDER BY created_at ASC, job_id ASC")
            }

            events: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in conn.execute("SELECT * FROM events ORDER BY timestamp ASC, event_id ASC"):
                events[str(row["session_id"])].append(
                    {
                        "event_id": row["event_id"],
                        "job_id": row["job_id"],
                        "session_id": row["session_id"],
                        "event_type": row["event_type"],
                        "timestamp": row["timestamp"],
                        "data": json_loads(row["data"], default={}),
                        "metadata": json_loads(row["metadata"], default={}),
                    }
                )

            artifacts: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in conn.execute("SELECT * FROM artifacts ORDER BY created_at ASC, artifact_id ASC"):
                artifacts[str(row["job_id"])].append(
                    {
                        "artifact_id": row["artifact_id"],
                        "job_id": row["job_id"],
                        "session_id": row["session_id"],
                        "artifact_type": row["artifact_type"],
                        "content": json_loads(row["content"], default=""),
                        "created_at": row["created_at"],
                        "created_by": row["created_by"],
                        "metadata": json_loads(row["metadata"], default={}),
                        "mime_type": row["mime_type"],
                    }
                )

            approvals = {
                str(row["approval_id"]): {
                    "approval_id": row["approval_id"],
                    "job_id": row["job_id"],
                    "session_id": row["session_id"],
                    "status": row["status"],
                    "requested_at": row["requested_at"],
                    "reason": row["reason"],
                    "content_preview": row["content_preview"],
                    "response_by": row["response_by"],
                    "responded_at": row["responded_at"],
                    "metadata": json_loads(row["metadata"], default={}),
                }
                for row in conn.execute("SELECT * FROM approvals ORDER BY requested_at ASC, approval_id ASC")
            }

            checkpoints: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in conn.execute("SELECT * FROM checkpoints ORDER BY created_at ASC, checkpoint_id ASC"):
                checkpoints[str(row["session_id"])].append(
                    {
                        "checkpoint_id": row["checkpoint_id"],
                        "session_id": row["session_id"],
                        "event_id": row["event_id"],
                        "created_at": row["created_at"],
                        "kind": row["kind"],
                        "metadata": json_loads(row["metadata"], default={}),
                    }
                )

            queue_row = conn.execute("SELECT value FROM runtime_meta WHERE key = ?", ("job_queue",)).fetchone()
            if queue_row is None:
                job_queue = [job_id for job_id, payload in jobs.items()]
            else:
                job_queue = [str(item) for item in json_loads(queue_row["value"], default=[])]

            return {
                "sessions": sessions,
                "jobs": jobs,
                "job_queue": job_queue,
                "events": dict(events),
                "artifacts": dict(artifacts),
                "approval_requests": approvals,
                "checkpoints": dict(checkpoints),
            }
        finally:
            conn.close()

    def _transcript_path(self, session_id: str) -> Path:
        return self.transcripts_dir / f"{session_id}.jsonl"

    def _spill_blob(self, payload: Any) -> dict[str, Any]:
        blob_id = f"blob_{os.urandom(8).hex()}"
        blob_path = self.blobs_dir / f"{blob_id}.json"
        blob_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        tmp_path = blob_path.with_suffix(".json.tmp")
        tmp_path.write_text(blob_text, encoding="utf-8")
        os.replace(tmp_path, blob_path)
        preview = blob_text[:512]
        return {
            "blob_id": blob_id,
            "blob_path": str(blob_path),
            "preview": preview,
            "size_bytes": len(blob_text.encode("utf-8")),
        }

    def _spill_threshold_bytes(self) -> int:
        """Spill threshold in bytes.

        Defaults to 64 KB (SPEC §S-1.3). `MODULAR_BLOB_SPILL_BYTES` env var lets
        operators / tests override the threshold. Non-positive / unparseable
        values fall back to the default.
        """
        raw = os.environ.get("MODULAR_BLOB_SPILL_BYTES")
        if raw is None:
            return 65_536
        try:
            parsed = int(raw)
        except ValueError:
            return 65_536
        return parsed if parsed > 0 else 65_536

    def _prepare_transcript_event(self, event: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(event)
        inner = payload.get("payload")
        # Idempotent: if this event was already spilled (e.g. we're re-writing
        # it through replace_transcript during repair), keep the existing
        # blob_ref — do not re-spill and orphan the original blob.
        if isinstance(inner, Mapping) and inner.get("inlined") is False and "blob_ref" in inner:
            return payload
        serialized_payload = json.dumps(inner, ensure_ascii=False, sort_keys=True)
        if len(serialized_payload.encode("utf-8")) > self._spill_threshold_bytes():
            payload = dict(payload)
            payload["payload"] = {
                "blob_ref": self._spill_blob(inner),
                "inlined": False,
            }
        return payload

    def _rehydrate_payload(self, payload: Any) -> Any:
        """Expand a blob_ref placeholder back into its original payload.

        Non-spilled payloads pass through unchanged. Missing / corrupt blobs
        leave the placeholder intact so callers can surface the problem
        instead of crashing mid-resume.
        """
        if not isinstance(payload, Mapping):
            return payload
        if payload.get("inlined") is not False:
            return payload
        blob_ref = payload.get("blob_ref")
        if not isinstance(blob_ref, Mapping):
            return payload
        blob_path_str = blob_ref.get("blob_path")
        if not blob_path_str:
            return payload
        blob_path = Path(blob_path_str)
        if not blob_path.exists():
            return payload
        try:
            return json.loads(blob_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return payload

    def append_transcript_event(self, session_id: str, event: Mapping[str, Any]) -> dict[str, Any]:
        prepared = self._prepare_transcript_event(event)
        transcript_path = self._transcript_path(session_id)
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        with transcript_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(prepared, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return prepared

    def replace_transcript(self, session_id: str, events: list[Mapping[str, Any]]) -> None:
        transcript_path = self._transcript_path(session_id)
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = transcript_path.with_suffix(".jsonl.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            for event in events:
                prepared = self._prepare_transcript_event(event)
                handle.write(json.dumps(prepared, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(tmp_path, transcript_path)

    def load_transcript(self, session_id: str, repair: bool = True) -> list[dict[str, Any]]:
        transcript_path = self._transcript_path(session_id)
        if not transcript_path.exists():
            return []

        recovered: list[dict[str, Any]] = []
        damaged = False
        with transcript_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    recovered.append(json.loads(stripped))
                except json.JSONDecodeError:
                    damaged = True
                    break

        if damaged and repair:
            # Pass the raw (still-spilled) events into repair so blob_refs are
            # preserved on-disk; _prepare_transcript_event is idempotent for
            # already-spilled payloads.
            self.replace_transcript(session_id, recovered)

        # Read-through: expand any blob_ref payloads so callers get the
        # original event exactly as it was appended.
        for event in recovered:
            if isinstance(event, dict) and "payload" in event:
                event["payload"] = self._rehydrate_payload(event["payload"])
        return recovered
