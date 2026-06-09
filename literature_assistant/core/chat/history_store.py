"""Durable chat history store for searchable, forkable SmartRead transcripts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
import json
import os
import sqlite3
from typing import Any, Literal
from uuid import uuid4

from db import json_dumps, json_loads, open_sqlite_connection
from project_paths import runtime_state_path


NodeRole = Literal["user", "assistant", "system", "tool"]
NodeType = Literal["message", "summary", "event", "attachment", "tool_use", "tool_result"]


def default_chat_history_db_path() -> Path:
    """Return the canonical local SQLite path for SmartRead history."""

    return runtime_state_path("chat_history", "chat_history.db")


class ChatHistoryStore:
    """SQLite + JSONL store for portable, searchable, forkable chat history.

    Args:
        db_path: SQLite database path. Runtime callers should use
            ``default_chat_history_db_path()``.

    Raises:
        TypeError: If ``db_path`` has an unsupported shape.
    """

    def __init__(self, db_path: str | Path):
        if not isinstance(db_path, str | Path):
            raise TypeError("db_path must be a string or pathlib.Path")
        self.db_path = Path(db_path).expanduser().resolve()
        self.storage_root = self.db_path.parent
        self.transcripts_dir = self.storage_root / "transcripts"
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        self._fts_enabled = self._ensure_schema()

    def _ensure_schema(self) -> bool:
        conn = open_sqlite_connection(self.db_path)
        fts_enabled = True
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    project_id TEXT,
                    title TEXT NOT NULL DEFAULT '',
                    mode TEXT NOT NULL DEFAULT 'literature_qa',
                    root_node_id TEXT,
                    head_node_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            self._ensure_column(conn, "conversations", "archived", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "conversations", "archived_at", "TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_nodes (
                    node_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    parent_node_id TEXT,
                    agent_id TEXT,
                    agent_role TEXT,
                    run_id TEXT,
                    role TEXT NOT NULL,
                    node_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    content_text TEXT NOT NULL DEFAULT '',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
                    FOREIGN KEY(parent_node_id) REFERENCES conversation_nodes(node_id) ON DELETE SET NULL
                )
                """
            )
            self._ensure_column(conn, "conversation_nodes", "agent_id", "TEXT")
            self._ensure_column(conn, "conversation_nodes", "agent_role", "TEXT")
            self._ensure_column(conn, "conversation_nodes", "run_id", "TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_agents (
                    agent_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    agent_role TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL DEFAULT '',
                    provider TEXT,
                    model TEXT,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY(agent_id, conversation_id),
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    run_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    parent_run_id TEXT,
                    status TEXT NOT NULL,
                    task_text TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS message_parts (
                    part_id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    part_index INTEGER NOT NULL,
                    part_type TEXT NOT NULL,
                    text TEXT NOT NULL DEFAULT '',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(node_id) REFERENCES conversation_nodes(node_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence_edges (
                    edge_id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    chunk_id TEXT,
                    material_id TEXT,
                    source TEXT NOT NULL DEFAULT '',
                    quote TEXT NOT NULL DEFAULT '',
                    page TEXT,
                    score REAL,
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(node_id) REFERENCES conversation_nodes(node_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS compression_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    covered_from_node_id TEXT,
                    covered_until_node_id TEXT,
                    covered_node_count INTEGER NOT NULL,
                    strategy TEXT NOT NULL,
                    summary_text TEXT NOT NULL,
                    original_estimated_tokens INTEGER NOT NULL DEFAULT 0,
                    target_tokens INTEGER NOT NULL DEFAULT 0,
                    keep_recent_turns INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_branches (
                    branch_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    base_node_id TEXT,
                    head_node_id TEXT,
                    title TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_events (
                    event_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_nodes_conversation ON conversation_nodes(conversation_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_nodes_parent ON conversation_nodes(parent_node_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_nodes_agent ON conversation_nodes(agent_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_nodes_run ON conversation_nodes(run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_nodes_created ON conversation_nodes(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_agents_conversation ON conversation_agents(conversation_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_agent_runs_conversation ON agent_runs(conversation_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_agent_runs_agent ON agent_runs(agent_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_parts_node ON message_parts(node_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_evidence_node ON evidence_edges(node_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_snapshots_conversation ON compression_snapshots(conversation_id)")
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS conversation_nodes_fts
                    USING fts5(node_id UNINDEXED, conversation_id UNINDEXED, content_text, evidence_text)
                    """
                )
            except sqlite3.Error:
                fts_enabled = False
            conn.commit()
            return fts_enabled
        finally:
            conn.close()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
        if not table_name.strip() or not column_name.strip() or not definition.strip():
            raise ValueError("table_name, column_name, and definition must be non-empty")
        columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})")}
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def _transcript_path(self, conversation_id: str) -> Path:
        normalized = self._require_non_empty_text(conversation_id, "conversation_id")
        return self.transcripts_dir / f"{normalized}.jsonl"

    @staticmethod
    def _require_non_empty_text(value: object, field_name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} must not be empty")
        return normalized

    @staticmethod
    def _coerce_json_mapping(value: Mapping[str, Any] | None, field_name: str) -> Mapping[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise TypeError(f"{field_name} must be a mapping or None")
        return value

    def _append_transcript_event(
        self,
        *,
        conversation_id: str,
        event_type: str,
        created_at: str,
        payload: Mapping[str, Any],
    ) -> None:
        event = {
            "schema_version": 1,
            "event_id": f"event_{uuid4().hex}",
            "conversation_id": conversation_id,
            "event_type": event_type,
            "created_at": created_at,
            "payload": dict(payload),
        }
        transcript_path = self._transcript_path(conversation_id)
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        with transcript_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def create_conversation(
        self,
        *,
        conversation_id: str,
        created_at: str,
        project_id: str | None = None,
        title: str = "",
        mode: str = "literature_qa",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Create a conversation row if it does not exist.

        Args:
            conversation_id: Stable public conversation identifier.
            created_at: ISO timestamp string.
            project_id: Optional Literature Assistant project id.
            title: Human-readable title.
            mode: SmartRead compatibility mode.
            metadata: JSON-safe metadata mapping.
        """

        normalized_id = self._require_non_empty_text(conversation_id, "conversation_id")
        normalized_time = self._require_non_empty_text(created_at, "created_at")
        normalized_mode = self._require_non_empty_text(mode, "mode")
        metadata_json = json_dumps(self._coerce_json_mapping(metadata, "metadata"))
        conn = open_sqlite_connection(self.db_path)
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO conversations (
                    conversation_id, project_id, title, mode, created_at, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (normalized_id, project_id, str(title or ""), normalized_mode, normalized_time, normalized_time, metadata_json),
            )
            conn.commit()
        finally:
            conn.close()
        self._append_transcript_event(
            conversation_id=normalized_id,
            event_type="conversation_created",
            created_at=normalized_time,
            payload={"project_id": project_id, "title": title, "mode": normalized_mode, "metadata": dict(metadata or {})},
        )

    def append_node(
        self,
        *,
        conversation_id: str,
        node_id: str,
        role: NodeRole,
        node_type: NodeType,
        created_at: str,
        content_text: str,
        parent_node_id: str | None = None,
        raw: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        parts: list[Mapping[str, Any]] | None = None,
        evidence_refs: list[Mapping[str, Any]] | None = None,
        agent_id: str | None = None,
        agent_role: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Append or upsert one history node and index its searchable text."""

        normalized_conversation_id = self._require_non_empty_text(conversation_id, "conversation_id")
        normalized_node_id = self._require_non_empty_text(node_id, "node_id")
        normalized_time = self._require_non_empty_text(created_at, "created_at")
        normalized_role = self._require_non_empty_text(role, "role")
        normalized_type = self._require_non_empty_text(node_type, "node_type")
        if normalized_role not in {"user", "assistant", "system", "tool"}:
            raise ValueError(f"unsupported role: {normalized_role}")
        if normalized_type not in {"message", "summary", "event", "attachment", "tool_use", "tool_result"}:
            raise ValueError(f"unsupported node_type: {normalized_type}")
        normalized_parent = parent_node_id.strip() if isinstance(parent_node_id, str) and parent_node_id.strip() else None
        normalized_agent_id = agent_id.strip() if isinstance(agent_id, str) and agent_id.strip() else None
        normalized_agent_role = agent_role.strip() if isinstance(agent_role, str) and agent_role.strip() else None
        normalized_run_id = run_id.strip() if isinstance(run_id, str) and run_id.strip() else None
        text = str(content_text or "")
        raw_json = json_dumps(self._coerce_json_mapping(raw, "raw"))
        metadata_json = json_dumps(self._coerce_json_mapping(metadata, "metadata"))
        safe_parts = parts or []
        safe_evidence = evidence_refs or []
        if not isinstance(safe_parts, list):
            raise TypeError("parts must be a list or None")
        if not isinstance(safe_evidence, list):
            raise TypeError("evidence_refs must be a list or None")

        conn = open_sqlite_connection(self.db_path)
        try:
            exists = conn.execute(
                "SELECT 1 FROM conversations WHERE conversation_id = ?",
                (normalized_conversation_id,),
            ).fetchone()
            if exists is None:
                conn.execute(
                    """
                    INSERT INTO conversations (
                        conversation_id, title, mode, created_at, updated_at, metadata_json
                    ) VALUES (?, '', 'literature_qa', ?, ?, '{}')
                    """,
                    (normalized_conversation_id, normalized_time, normalized_time),
                )
            conn.execute(
                """
                INSERT OR REPLACE INTO conversation_nodes (
                    node_id, conversation_id, parent_node_id, agent_id, agent_role, run_id, role, node_type,
                    created_at, content_text, raw_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_node_id,
                    normalized_conversation_id,
                    normalized_parent,
                    normalized_agent_id,
                    normalized_agent_role,
                    normalized_run_id,
                    normalized_role,
                    normalized_type,
                    normalized_time,
                    text,
                    raw_json,
                    metadata_json,
                ),
            )
            conn.execute("DELETE FROM message_parts WHERE node_id = ?", (normalized_node_id,))
            for index, part in enumerate(safe_parts):
                if not isinstance(part, Mapping):
                    raise TypeError("each message part must be a mapping")
                conn.execute(
                    """
                    INSERT INTO message_parts (
                        part_id, node_id, part_index, part_type, text, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(part.get("part_id") or f"part_{uuid4().hex}"),
                        normalized_node_id,
                        index,
                        str(part.get("part_type") or part.get("type") or "text"),
                        str(part.get("text") or ""),
                        json_dumps(dict(part)),
                    ),
                )
            conn.execute("DELETE FROM evidence_edges WHERE node_id = ?", (normalized_node_id,))
            evidence_texts: list[str] = []
            for ref in safe_evidence:
                if not isinstance(ref, Mapping):
                    raise TypeError("each evidence ref must be a mapping")
                quote = str(ref.get("quote") or ref.get("text") or "")
                evidence_texts.append(quote)
                raw_score = ref.get("score")
                score = float(raw_score) if isinstance(raw_score, int | float) else None
                conn.execute(
                    """
                    INSERT INTO evidence_edges (
                        edge_id, node_id, chunk_id, material_id, source, quote, page, score, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"edge_{uuid4().hex}",
                        normalized_node_id,
                        ref.get("chunk_id"),
                        ref.get("material_id"),
                        str(ref.get("source") or ""),
                        quote,
                        None if ref.get("page") is None else str(ref.get("page")),
                        score,
                        json_dumps(dict(ref)),
                    ),
                )
            if self._fts_enabled:
                conn.execute("DELETE FROM conversation_nodes_fts WHERE node_id = ?", (normalized_node_id,))
                conn.execute(
                    """
                    INSERT INTO conversation_nodes_fts (
                        node_id, conversation_id, content_text, evidence_text
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (normalized_node_id, normalized_conversation_id, text, "\n".join(evidence_texts)),
                )
            root_node_id = conn.execute(
                """
                SELECT root_node_id FROM conversations WHERE conversation_id = ?
                """,
                (normalized_conversation_id,),
            ).fetchone()
            next_root = normalized_node_id
            if root_node_id is not None and root_node_id["root_node_id"]:
                next_root = str(root_node_id["root_node_id"])
            conn.execute(
                """
                UPDATE conversations
                SET root_node_id = ?, head_node_id = ?, updated_at = ?
                WHERE conversation_id = ?
                """,
                (next_root, normalized_node_id, normalized_time, normalized_conversation_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        self._append_transcript_event(
            conversation_id=normalized_conversation_id,
            event_type="node_appended",
            created_at=normalized_time,
            payload={
                "node_id": normalized_node_id,
                "parent_node_id": normalized_parent,
                "agent_id": normalized_agent_id,
                "agent_role": normalized_agent_role,
                "run_id": normalized_run_id,
                "role": normalized_role,
                "node_type": normalized_type,
            },
        )

    def upsert_agent(
        self,
        *,
        conversation_id: str,
        agent_id: str,
        created_at: str,
        agent_role: str = "",
        display_name: str = "",
        provider: str | None = None,
        model: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Register one agent participant for a conversation."""

        normalized_conversation_id = self._require_non_empty_text(conversation_id, "conversation_id")
        normalized_agent_id = self._require_non_empty_text(agent_id, "agent_id")
        normalized_time = self._require_non_empty_text(created_at, "created_at")
        conn = open_sqlite_connection(self.db_path)
        try:
            exists = conn.execute(
                "SELECT 1 FROM conversations WHERE conversation_id = ?",
                (normalized_conversation_id,),
            ).fetchone()
            if exists is None:
                conn.execute(
                    """
                    INSERT INTO conversations (
                        conversation_id, title, mode, created_at, updated_at, metadata_json
                    ) VALUES (?, '', 'literature_qa', ?, ?, '{}')
                    """,
                    (normalized_conversation_id, normalized_time, normalized_time),
                )
            conn.execute(
                """
                INSERT OR REPLACE INTO conversation_agents (
                    agent_id, conversation_id, agent_role, display_name, provider,
                    model, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_agent_id,
                    normalized_conversation_id,
                    str(agent_role or ""),
                    str(display_name or ""),
                    provider,
                    model,
                    normalized_time,
                    json_dumps(self._coerce_json_mapping(metadata, "metadata")),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        self._append_transcript_event(
            conversation_id=normalized_conversation_id,
            event_type="agent_registered",
            created_at=normalized_time,
            payload={
                "agent_id": normalized_agent_id,
                "agent_role": agent_role,
                "display_name": display_name,
                "provider": provider,
                "model": model,
            },
        )

    def create_agent_run(
        self,
        *,
        conversation_id: str,
        agent_id: str,
        run_id: str,
        created_at: str,
        task_text: str = "",
        status: str = "running",
        parent_run_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Create or update one agent run inside a conversation."""

        normalized_conversation_id = self._require_non_empty_text(conversation_id, "conversation_id")
        normalized_agent_id = self._require_non_empty_text(agent_id, "agent_id")
        normalized_run_id = self._require_non_empty_text(run_id, "run_id")
        normalized_time = self._require_non_empty_text(created_at, "created_at")
        normalized_status = self._require_non_empty_text(status, "status")
        conn = open_sqlite_connection(self.db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_runs (
                    run_id, conversation_id, agent_id, parent_run_id, status,
                    task_text, created_at, completed_at, metadata_json
                ) VALUES (
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    (SELECT completed_at FROM agent_runs WHERE run_id = ?),
                    ?
                )
                """,
                (
                    normalized_run_id,
                    normalized_conversation_id,
                    normalized_agent_id,
                    parent_run_id,
                    normalized_status,
                    str(task_text or ""),
                    normalized_time,
                    normalized_run_id,
                    json_dumps(self._coerce_json_mapping(metadata, "metadata")),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        self._append_transcript_event(
            conversation_id=normalized_conversation_id,
            event_type="agent_run_created",
            created_at=normalized_time,
            payload={"run_id": normalized_run_id, "agent_id": normalized_agent_id, "status": normalized_status},
        )

    def create_compression_snapshot(
        self,
        *,
        conversation_id: str,
        created_at: str,
        summary_text: str,
        covered_node_count: int,
        strategy: str,
        covered_from_node_id: str | None = None,
        covered_until_node_id: str | None = None,
        original_estimated_tokens: int = 0,
        target_tokens: int = 0,
        keep_recent_turns: int = 0,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        """Persist a derived compression snapshot without mutating messages."""

        normalized_conversation_id = self._require_non_empty_text(conversation_id, "conversation_id")
        normalized_time = self._require_non_empty_text(created_at, "created_at")
        normalized_strategy = self._require_non_empty_text(strategy, "strategy")
        if not isinstance(covered_node_count, int) or covered_node_count < 0:
            raise ValueError("covered_node_count must be a non-negative integer")
        if not isinstance(original_estimated_tokens, int) or original_estimated_tokens < 0:
            raise ValueError("original_estimated_tokens must be a non-negative integer")
        if not isinstance(target_tokens, int) or target_tokens < 0:
            raise ValueError("target_tokens must be a non-negative integer")
        if not isinstance(keep_recent_turns, int) or keep_recent_turns < 0:
            raise ValueError("keep_recent_turns must be a non-negative integer")
        snapshot_id = f"snapshot_{uuid4().hex}"
        conn = open_sqlite_connection(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO compression_snapshots (
                    snapshot_id, conversation_id, covered_from_node_id, covered_until_node_id,
                    covered_node_count, strategy, summary_text, original_estimated_tokens,
                    target_tokens, keep_recent_turns, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    normalized_conversation_id,
                    covered_from_node_id,
                    covered_until_node_id,
                    covered_node_count,
                    normalized_strategy,
                    str(summary_text or ""),
                    original_estimated_tokens,
                    target_tokens,
                    keep_recent_turns,
                    normalized_time,
                    json_dumps(self._coerce_json_mapping(metadata, "metadata")),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        self._append_transcript_event(
            conversation_id=normalized_conversation_id,
            event_type="compression_created",
            created_at=normalized_time,
            payload={"snapshot_id": snapshot_id, "covered_until_node_id": covered_until_node_id},
        )
        return snapshot_id

    def fork_conversation(
        self,
        *,
        conversation_id: str,
        base_node_id: str,
        branch_id: str,
        created_at: str,
        title: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Create a branch that can continue from an existing history node."""

        normalized_conversation_id = self._require_non_empty_text(conversation_id, "conversation_id")
        normalized_base = self._require_non_empty_text(base_node_id, "base_node_id")
        normalized_branch = self._require_non_empty_text(branch_id, "branch_id")
        normalized_time = self._require_non_empty_text(created_at, "created_at")
        conn = open_sqlite_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT 1 FROM conversation_nodes
                WHERE conversation_id = ? AND node_id = ?
                """,
                (normalized_conversation_id, normalized_base),
            ).fetchone()
            if row is None:
                raise ValueError("base_node_id must exist in conversation")
            conn.execute(
                """
                INSERT OR REPLACE INTO conversation_branches (
                    branch_id, conversation_id, base_node_id, head_node_id,
                    title, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_branch,
                    normalized_conversation_id,
                    normalized_base,
                    normalized_base,
                    str(title or ""),
                    normalized_time,
                    json_dumps(self._coerce_json_mapping(metadata, "metadata")),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        self._append_transcript_event(
            conversation_id=normalized_conversation_id,
            event_type="branch_created",
            created_at=normalized_time,
            payload={"branch_id": normalized_branch, "base_node_id": normalized_base},
        )

    def import_legacy_session(self, session: Mapping[str, Any]) -> dict[str, Any]:
        """Import one legacy JSON SmartRead session into the history store.

        Args:
            session: Legacy session mapping with ``session_id`` and
                ``messages``.

        Returns:
            Counts for imported messages and compression snapshots.
        """

        if not isinstance(session, Mapping):
            raise TypeError("session must be a mapping")
        session_id = self._require_non_empty_text(str(session.get("session_id") or ""), "session.session_id")
        created_at = str(session.get("created_at") or session.get("updated_at") or "1970-01-01T00:00:00Z")
        updated_at = str(session.get("updated_at") or created_at)
        self.create_conversation(
            conversation_id=session_id,
            created_at=created_at,
            title=str(session.get("title") or ""),
            mode=str(session.get("mode") or "literature_qa"),
            metadata={"legacy_imported": True, "updated_at": updated_at},
        )
        self.upsert_agent(
            conversation_id=session_id,
            agent_id="user",
            agent_role="user",
            display_name="用户",
            created_at=created_at,
            metadata={"legacy_imported": True},
        )
        self.upsert_agent(
            conversation_id=session_id,
            agent_id="smart_read_assistant",
            agent_role="assistant",
            display_name="智能研读助手",
            created_at=created_at,
            metadata={"legacy_imported": True},
        )
        messages = session.get("messages")
        if not isinstance(messages, list):
            messages = []
        parent_node_id: str | None = None
        imported_messages = 0
        for index, message in enumerate(messages):
            if not isinstance(message, Mapping):
                continue
            node_id = str(message.get("id") or f"{session_id}_message_{index}")
            role = str(message.get("role") or "system")
            if role not in {"user", "assistant", "system", "tool"}:
                role = "system"
            created = str(message.get("timestamp") or created_at)
            evidence_refs = message.get("evidence_refs")
            self.append_node(
                conversation_id=session_id,
                node_id=node_id,
                parent_node_id=parent_node_id,
                role=role,  # type: ignore[arg-type]
                node_type="message",
                created_at=created,
                content_text=str(message.get("content") or ""),
                raw=dict(message),
                evidence_refs=evidence_refs if isinstance(evidence_refs, list) else None,
                agent_id="smart_read_assistant" if role == "assistant" else "user",
                agent_role=role,
            )
            parent_node_id = node_id
            imported_messages += 1
        compression = session.get("compression")
        imported_snapshots = 0
        if isinstance(compression, Mapping) and str(compression.get("summary") or "").strip():
            self.create_compression_snapshot(
                conversation_id=session_id,
                created_at=str(compression.get("created_at") or updated_at),
                summary_text=str(compression.get("summary") or ""),
                covered_node_count=int(compression.get("covered_message_count") or 0),
                strategy=str(compression.get("strategy") or "deterministic_extractive_v1"),
                covered_until_node_id=(
                    str(compression.get("covered_until_message_id"))
                    if compression.get("covered_until_message_id") is not None
                    else None
                ),
                original_estimated_tokens=int(compression.get("original_estimated_tokens") or 0),
                target_tokens=int(compression.get("target_tokens") or 0),
                keep_recent_turns=int(compression.get("keep_recent_turns") or 0),
                metadata={"legacy_session_id": session_id},
            )
            imported_snapshots = 1
        return {"conversation_id": session_id, "messages": imported_messages, "compression_snapshots": imported_snapshots}

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Search message text and evidence quotes.

        Args:
            query: Non-empty FTS or substring query.
            limit: Maximum result count.

        Returns:
            Ordered result mappings with conversation/node identifiers.
        """

        normalized_query = self._require_non_empty_text(query, "query")
        if not isinstance(limit, int) or limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        conn = open_sqlite_connection(self.db_path)
        try:
            if self._fts_enabled:
                rows = conn.execute(
                    """
                    SELECT n.node_id, n.conversation_id, n.role, n.node_type,
                           snippet(conversation_nodes_fts, 2, '<mark>', '</mark>', '...', 16) AS snippet
                    FROM conversation_nodes_fts
                    JOIN conversation_nodes AS n ON n.node_id = conversation_nodes_fts.node_id
                    JOIN conversations AS c ON c.conversation_id = n.conversation_id
                    WHERE conversation_nodes_fts MATCH ?
                      AND COALESCE(c.archived, 0) = 0
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (normalized_query, limit),
                ).fetchall()
                if not rows:
                    rows = self._search_like(conn, normalized_query, limit)
            else:
                rows = self._search_like(conn, normalized_query, limit)
            return [
                {
                    "node_id": row["node_id"],
                    "conversation_id": row["conversation_id"],
                    "role": row["role"],
                    "node_type": row["node_type"],
                    "snippet": row["snippet"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    @staticmethod
    def _search_like(conn: sqlite3.Connection, query: str, limit: int) -> list[sqlite3.Row]:
        pattern = f"%{query}%"
        return list(
            conn.execute(
                """
                SELECT n.node_id, n.conversation_id, n.role, n.node_type, n.content_text AS snippet
                FROM conversation_nodes AS n
                JOIN conversations AS c ON c.conversation_id = n.conversation_id
                WHERE COALESCE(c.archived, 0) = 0
                  AND (n.content_text LIKE ?
                   OR n.node_id IN (
                       SELECT node_id FROM evidence_edges WHERE quote LIKE ?
                   ))
                ORDER BY n.created_at DESC
                LIMIT ?
                """,
                (pattern, pattern, limit),
            ).fetchall()
        )

    def set_conversation_archived(
        self,
        conversation_id: str,
        *,
        archived: bool,
        archived_at: str | None = None,
    ) -> bool:
        """
        Mark one conversation archived or active in the durable history index.

        Args:
            conversation_id: Existing conversation identifier.
            archived: True to hide it from active search results.
            archived_at: Optional ISO timestamp recorded when archiving.

        Returns:
            True when a row was updated.
        """
        normalized_id = self._require_non_empty_text(conversation_id, "conversation_id")
        if not isinstance(archived, bool):
            raise TypeError("archived must be a boolean")
        next_archived_at = archived_at if archived else None
        conn = open_sqlite_connection(self.db_path)
        try:
            cursor = conn.execute(
                """
                UPDATE conversations
                SET archived = ?, archived_at = ?
                WHERE conversation_id = ?
                """,
                (1 if archived else 0, next_archived_at, normalized_id),
            )
            conn.commit()
            updated = cursor.rowcount > 0
        finally:
            conn.close()
        if updated:
            event_time = next_archived_at or datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
            self._append_transcript_event(
                conversation_id=normalized_id,
                event_type="conversation_archived" if archived else "conversation_restored",
                created_at=event_time,
                payload={"archived": archived, "archived_at": next_archived_at},
            )
        return updated

    def delete_conversation(self, conversation_id: str, *, delete_transcript: bool = True) -> bool:
        """
        Delete one durable conversation and its search index rows.

        Args:
            conversation_id: Existing conversation identifier.
            delete_transcript: Also remove the JSONL transcript file.

        Returns:
            True when a conversation row existed and was deleted.
        """
        normalized_id = self._require_non_empty_text(conversation_id, "conversation_id")
        conn = open_sqlite_connection(self.db_path)
        try:
            exists = conn.execute(
                "SELECT 1 FROM conversations WHERE conversation_id = ?",
                (normalized_id,),
            ).fetchone()
            if exists is None:
                return False
            if self._fts_enabled:
                conn.execute(
                    "DELETE FROM conversation_nodes_fts WHERE conversation_id = ?",
                    (normalized_id,),
                )
            conn.execute("DELETE FROM conversations WHERE conversation_id = ?", (normalized_id,))
            conn.commit()
        finally:
            conn.close()

        if delete_transcript:
            try:
                self._transcript_path(normalized_id).unlink(missing_ok=True)
            except OSError:
                pass
        return True

    def list_agents(self, conversation_id: str) -> list[dict[str, Any]]:
        """Return registered agent participants for a conversation."""

        normalized_id = self._require_non_empty_text(conversation_id, "conversation_id")
        conn = open_sqlite_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT * FROM conversation_agents
                WHERE conversation_id = ?
                ORDER BY created_at ASC, agent_id ASC
                """,
                (normalized_id,),
            ).fetchall()
            return [
                {
                    "agent_id": row["agent_id"],
                    "conversation_id": row["conversation_id"],
                    "agent_role": row["agent_role"],
                    "display_name": row["display_name"],
                    "provider": row["provider"],
                    "model": row["model"],
                    "created_at": row["created_at"],
                    "metadata": json_loads(row["metadata_json"], default={}),
                }
                for row in rows
            ]
        finally:
            conn.close()

    def load_transcript(self, conversation_id: str) -> list[dict[str, Any]]:
        """Load JSONL transcript events for one conversation."""

        path = self._transcript_path(conversation_id)
        if not path.exists():
            return []
        events: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                payload = json.loads(stripped)
                if isinstance(payload, dict):
                    events.append(payload)
        return events

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """Return one conversation row with decoded metadata."""

        normalized_id = self._require_non_empty_text(conversation_id, "conversation_id")
        conn = open_sqlite_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM conversations WHERE conversation_id = ?",
                (normalized_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "conversation_id": row["conversation_id"],
                "project_id": row["project_id"],
                "title": row["title"],
                "mode": row["mode"],
                "root_node_id": row["root_node_id"],
                "head_node_id": row["head_node_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "archived": bool(row["archived"]),
                "archived_at": row["archived_at"],
                "metadata": json_loads(row["metadata_json"], default={}),
            }
        finally:
            conn.close()
