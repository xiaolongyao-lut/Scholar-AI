"""Durable chat history store for searchable, forkable SmartRead transcripts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
import hashlib
import json
import math
import os
import re
import sqlite3
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

if TYPE_CHECKING:
    from literature_assistant.core.db import json_dumps, json_loads, open_sqlite_connection
    from literature_assistant.core.project_paths import runtime_state_path
else:
    from db import json_dumps, json_loads, open_sqlite_connection
    from project_paths import runtime_state_path

from .visual_observation import (
    VisualObservationCandidate,
    VisualObservationFreshnessStatus,
    VisualObservationLifecycleAxis,
    VisualObservationLifecycleEvent,
    VisualObservationLifecycleReceipt,
    VisualObservationLifecycleRequest,
    VisualObservationLifecycleStatus,
    VisualObservationMutationResult,
    VisualObservationReviewStatus,
    VisualObservationSourceRevisionApplyReceipt,
    VisualObservationSourceRevisionApplyRequest,
    VisualObservationSourceRevisionIdentity,
    VisualObservationSourceRevisionImpact,
    VisualObservationSourceRevisionOperation,
    VisualObservationSourceRevisionPreflight,
    VisualObservationSourceRevisionResult,
    evaluate_visual_observation_freshness_transition,
    evaluate_visual_observation_transition,
    sanitize_visual_observation_refs,
    sanitize_visual_observations,
    visual_observation_lifecycle_request_hash,
    visual_observation_reference,
    visual_observation_source_revision_impact_fingerprint,
    visual_observation_source_revision_request_hash,
)


NodeRole = Literal["user", "assistant", "system", "tool"]
NodeType = Literal["message", "summary", "event", "attachment", "tool_use", "tool_result"]
ANSWER_RECEIPT_SCHEMA_VERSION = "scholar-ai-answer-receipt/v1"
ANSWER_RECORD_SCHEMA_VERSION = "scholar-ai-answer-record/v1"
RESEARCH_SELECTION_SCHEMA_VERSION = "scholar-ai-research-selection/v1"
CONVERSATION_TOMBSTONE_SCHEMA_VERSION = "scholar-ai-conversation-tombstone/v1"
_RESEARCH_SELECTION_KINDS = frozenset({"text", "figure", "table", "formula", "region"})
_RESEARCH_SELECTION_BBOX_UNITS = frozenset(
    {"normalized_ratio", "normalized_1000", "pdf_points", "css_pixels"}
)
_RESEARCH_SELECTION_MAX_COUNT = 12
_VISUAL_SOURCE_REVISION_MAX_IMPACTS = 500
_VISUAL_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


class VisualObservationStoreError(RuntimeError):
    """Base failure for durable visual-observation lifecycle storage."""


class VisualObservationConflictError(VisualObservationStoreError):
    """A lifecycle CAS or idempotency precondition no longer matches."""


class VisualObservationCorruptionError(VisualObservationStoreError):
    """Persisted visual-observation lifecycle data is internally inconsistent."""


def _visual_identifier(value: str, field_name: str) -> str:
    """Return one bounded lifecycle identifier."""

    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _VISUAL_IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} has an unsupported identifier shape")
    return normalized


def _visual_datetime(value: str | datetime, field_name: str) -> datetime:
    """Parse one timezone-aware visual lifecycle timestamp as UTC."""

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    else:
        raise TypeError(f"{field_name} must be a string or datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)


def _visual_timestamp(value: datetime) -> str:
    """Render one UTC lifecycle timestamp in stable JSON form."""

    normalized = _visual_datetime(value, "timestamp")
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _next_visual_timestamp(
    *previous_values: str,
    requested: datetime | None = None,
) -> datetime:
    """Return a UTC timestamp strictly newer than all candidate snapshots."""

    candidate = datetime.now(UTC) if requested is None else _visual_datetime(requested, "occurred_at")
    if previous_values:
        latest = max(_visual_datetime(value, "updated_at") for value in previous_values)
        if candidate <= latest:
            candidate = latest + timedelta(microseconds=1)
    return candidate


def _bounded_optional_text(value: object, max_length: int) -> str | None:
    """Return one trimmed optional history field without coercing unknown types."""

    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized[:max_length] or None


def _safe_research_bbox(value: object, unit: str) -> list[float] | None:
    """Validate one persisted bbox without importing request-layer models."""

    if not isinstance(value, list) or len(value) != 4:
        return None
    if any(isinstance(item, bool) or not isinstance(item, int | float) for item in value):
        return None
    bbox = [float(item) for item in value]
    if not all(math.isfinite(item) for item in bbox):
        return None
    x, y, width, height = bbox
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        return None
    if unit == "normalized_ratio" and (x > 1 or y > 1 or x + width > 1.0001 or y + height > 1.0001):
        return None
    if unit == "normalized_1000" and (x > 1000 or y > 1000 or x + width > 1000.1 or y + height > 1000.1):
        return None
    return bbox


def sanitize_research_selections(value: object) -> list[dict[str, Any]]:
    """Return bounded, JSON-safe user selections for durable chat history.

    Request-only image indexes, encoded pixels, asset paths, and unknown keys
    are intentionally omitted. Invalid entries are dropped independently so a
    malformed legacy record cannot make the rest of a session unreadable.
    """

    if not isinstance(value, list):
        return []
    selections: list[dict[str, Any]] = []
    selection_ids: set[str] = set()
    group_orders: set[tuple[str, int]] = set()
    for item in value[:_RESEARCH_SELECTION_MAX_COUNT]:
        if not isinstance(item, Mapping):
            continue
        raw_schema = item.get("schema_version")
        if raw_schema not in {None, RESEARCH_SELECTION_SCHEMA_VERSION}:
            continue
        kind = _bounded_optional_text(item.get("kind"), 16)
        selection_id = _bounded_optional_text(item.get("selection_id"), 256)
        selection_turn_id = _bounded_optional_text(item.get("turn_id"), 256)
        group_id = _bounded_optional_text(item.get("group_id"), 256)
        order = item.get("order")
        material_id = _bounded_optional_text(item.get("material_id"), 256)
        page = item.get("page")
        if (
            kind not in _RESEARCH_SELECTION_KINDS
            or not selection_id
            or not selection_turn_id
            or not group_id
            or not material_id
        ):
            continue
        if isinstance(order, bool) or not isinstance(order, int) or not 0 <= order < _RESEARCH_SELECTION_MAX_COUNT:
            continue
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            continue
        if selection_id in selection_ids or (group_id, order) in group_orders:
            continue
        text = _bounded_optional_text(item.get("text"), 4000)
        label = _bounded_optional_text(item.get("label"), 160)
        chunk_id = _bounded_optional_text(item.get("chunk_id"), 256)
        candidate_id = _bounded_optional_text(item.get("candidate_id"), 256)
        raw_unit = _bounded_optional_text(item.get("bbox_unit"), 32)
        bbox_unit = raw_unit if raw_unit in _RESEARCH_SELECTION_BBOX_UNITS else None
        bbox = (
            _safe_research_bbox(item.get("bbox"), bbox_unit)
            if bbox_unit is not None
            else None
        )
        if kind == "text" and not text:
            continue
        if kind != "text" and bbox is None:
            continue
        selections.append(
            {
                "schema_version": RESEARCH_SELECTION_SCHEMA_VERSION,
                "selection_id": selection_id,
                "turn_id": selection_turn_id,
                "group_id": group_id,
                "order": order,
                "material_id": material_id,
                "kind": kind,
                "page": page,
                "bbox": bbox,
                "bbox_unit": bbox_unit if bbox is not None else None,
                "text": text,
                "label": label,
                "chunk_id": chunk_id,
                "candidate_id": candidate_id,
            }
        )
        selection_ids.add(selection_id)
        group_orders.add((group_id, order))
    return sorted(selections, key=lambda selection: int(selection["order"]))


def default_chat_history_db_path() -> Path:
    """Return the canonical local SQLite path for SmartRead history."""

    return Path(runtime_state_path("chat_history", "chat_history.db"))


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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS visual_observation_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    project_id TEXT,
                    turn_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    observation_order INTEGER NOT NULL,
                    route TEXT NOT NULL,
                    generation_status TEXT NOT NULL,
                    review_status TEXT NOT NULL,
                    cache_status TEXT NOT NULL,
                    cache_key_hash TEXT,
                    output_sha256 TEXT,
                    origin_node_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL
                )
                """
            )
            self._ensure_column(
                conn,
                "visual_observation_candidates",
                "freshness_status",
                "TEXT NOT NULL DEFAULT 'fresh'",
            )
            self._ensure_column(
                conn,
                "visual_observation_candidates",
                "project_id",
                "TEXT",
            )
            conn.execute(
                """
                UPDATE visual_observation_candidates
                SET review_status = 'candidate', freshness_status = 'stale'
                WHERE review_status = 'stale'
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS visual_observation_source_bindings (
                    candidate_id TEXT NOT NULL,
                    source_fingerprint TEXT NOT NULL,
                    PRIMARY KEY(candidate_id, source_fingerprint),
                    FOREIGN KEY(candidate_id)
                        REFERENCES visual_observation_candidates(candidate_id)
                        ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS visual_observation_lifecycle_events (
                    event_id TEXT PRIMARY KEY,
                    operation_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    project_id TEXT,
                    axis TEXT NOT NULL CHECK(axis IN ('review', 'freshness')),
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    FOREIGN KEY(candidate_id)
                        REFERENCES visual_observation_candidates(candidate_id)
                        ON DELETE RESTRICT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS visual_observation_lifecycle_receipts (
                    operation_id TEXT PRIMARY KEY,
                    receipt_id TEXT NOT NULL UNIQUE,
                    event_id TEXT NOT NULL UNIQUE,
                    candidate_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    project_id TEXT,
                    request_sha256 TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    candidate_raw_json TEXT NOT NULL,
                    FOREIGN KEY(event_id)
                        REFERENCES visual_observation_lifecycle_events(event_id)
                        ON DELETE RESTRICT,
                    FOREIGN KEY(candidate_id)
                        REFERENCES visual_observation_candidates(candidate_id)
                        ON DELETE RESTRICT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS visual_observation_source_revision_receipts (
                    operation_id TEXT PRIMARY KEY,
                    receipt_id TEXT NOT NULL UNIQUE,
                    project_id TEXT NOT NULL,
                    operation TEXT NOT NULL CHECK(operation IN ('mark_stale', 'revalidate')),
                    request_sha256 TEXT NOT NULL,
                    impact_fingerprint TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL
                )
                """
            )
            existing_visual_rows = conn.execute(
                """
                SELECT candidate_id, project_id, raw_json
                FROM visual_observation_candidates
                """
            ).fetchall()
            for row in existing_visual_rows:
                raw = json_loads(row["raw_json"], default={})
                sanitized = sanitize_visual_observations([raw])
                if not sanitized:
                    continue
                candidate = VisualObservationCandidate.model_validate(sanitized[0])
                if not str(row["project_id"] or "").strip() and candidate.project_id:
                    conn.execute(
                        """
                        UPDATE visual_observation_candidates
                        SET project_id = ?
                        WHERE candidate_id = ? AND (project_id IS NULL OR project_id = '')
                        """,
                        (candidate.project_id, candidate.candidate_id),
                    )
                has_source_bindings = conn.execute(
                    """
                    SELECT 1
                    FROM visual_observation_source_bindings
                    WHERE candidate_id = ?
                    LIMIT 1
                    """,
                    (candidate.candidate_id,),
                ).fetchone()
                if has_source_bindings is None:
                    for source_fingerprint in candidate.source_fingerprints:
                        conn.execute(
                            """
                            INSERT INTO visual_observation_source_bindings (
                                candidate_id, source_fingerprint
                            ) VALUES (?, ?)
                            """,
                            (candidate.candidate_id, source_fingerprint),
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
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_visual_observation_session_turn "
                "ON visual_observation_candidates(session_id, turn_id, observation_order)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_visual_observation_status "
                "ON visual_observation_candidates(generation_status, review_status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_visual_observation_lifecycle "
                "ON visual_observation_candidates(review_status, freshness_status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_visual_observation_cache "
                "ON visual_observation_candidates(cache_key_hash)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_visual_observation_project "
                "ON visual_observation_candidates(project_id, freshness_status, candidate_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_visual_observation_source_binding "
                "ON visual_observation_source_bindings(source_fingerprint, candidate_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_visual_observation_events_candidate "
                "ON visual_observation_lifecycle_events(candidate_id, occurred_at, event_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_visual_observation_events_operation "
                "ON visual_observation_lifecycle_events(operation_id, event_id)"
            )
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

    @staticmethod
    def _bounded_mapping_items(raw_items: object, *, limit: int = 20) -> list[dict[str, Any]]:
        """Return JSON-safe bounded mappings without raw text-heavy fields."""

        if not isinstance(raw_items, list):
            return []
        output: list[dict[str, Any]] = []
        denied_keys = {"content", "raw_content", "text", "quote", "private_reasoning", "chain_of_thought"}
        for item in raw_items:
            if not isinstance(item, Mapping):
                continue
            compact: dict[str, Any] = {}
            for key, value in item.items():
                key_text = str(key or "").strip()
                if not key_text or key_text in denied_keys:
                    continue
                if isinstance(value, str):
                    compact[key_text] = value[:500]
                elif isinstance(value, bool | int | float) or value is None:
                    compact[key_text] = value
                elif isinstance(value, list):
                    compact[key_text] = [
                        entry if (isinstance(entry, bool | int | float) or entry is None) else str(entry)[:200]
                        for entry in value[:16]
                    ]
                elif isinstance(value, Mapping):
                    compact[key_text] = {
                        str(inner_key): str(inner_value)[:200]
                        for inner_key, inner_value in list(value.items())[:16]
                        if str(inner_key or "").strip()
                    }
            if compact:
                output.append(compact)
            if len(output) >= limit:
                break
        return output

    @classmethod
    def _bounded_json_mapping(
        cls,
        raw: object,
        *,
        max_entries: int = 32,
        max_list_items: int = 16,
        max_string_chars: int = 500,
        depth: int = 3,
    ) -> dict[str, Any]:
        """Return a bounded JSON-safe mapping for receipt lookup metadata."""

        if not isinstance(raw, Mapping) or depth < 0:
            return {}
        denied_keys = {"content", "raw_content", "text", "quote", "private_reasoning", "chain_of_thought"}
        compact: dict[str, Any] = {}
        for key, value in list(raw.items())[:max_entries]:
            key_text = str(key or "").strip()
            if not key_text or key_text in denied_keys:
                continue
            if isinstance(value, str):
                compact[key_text] = value[:max_string_chars]
            elif isinstance(value, (bool, int, float)) or value is None:
                compact[key_text] = value
            elif isinstance(value, Mapping):
                nested = cls._bounded_json_mapping(
                    value,
                    max_entries=max_entries,
                    max_list_items=max_list_items,
                    max_string_chars=max_string_chars,
                    depth=depth - 1,
                )
                if nested:
                    compact[key_text] = nested
            elif isinstance(value, list) and depth > 0:
                items: list[Any] = []
                for entry in value[:max_list_items]:
                    if isinstance(entry, str):
                        items.append(entry[:max_string_chars])
                    elif isinstance(entry, (bool, int, float)) or entry is None:
                        items.append(entry)
                    elif isinstance(entry, Mapping):
                        nested_entry = cls._bounded_json_mapping(
                            entry,
                            max_entries=max_entries,
                            max_list_items=max_list_items,
                            max_string_chars=max_string_chars,
                            depth=depth - 1,
                        )
                        if nested_entry:
                            items.append(nested_entry)
                    else:
                        items.append(str(entry)[:max_string_chars])
                compact[key_text] = items
            else:
                compact[key_text] = str(value)[:max_string_chars]
        return compact

    @classmethod
    def _answer_origin_for_receipt(cls, raw_origin: object) -> str:
        origin = str(raw_origin or "").strip()
        if origin == "external_agent":
            return "host_agent"
        return "scholar_ai_model"

    @classmethod
    def _answer_receipt_from_message(
        cls,
        *,
        session: Mapping[str, Any],
        message: Mapping[str, Any],
        updated_at: str,
        question: str = "",
    ) -> dict[str, Any] | None:
        """Lift one assistant message into the additive answer receipt contract."""

        generated_in = str(message.get("generated_in") or session.get("generated_in") or "").strip()
        evidence_pack_ref = str(message.get("evidence_pack_ref") or "").strip()
        raw_retrieval_diagnostics = message.get("retrieval_diagnostics")
        retrieval_diagnostics = (
            dict(raw_retrieval_diagnostics)
            if isinstance(raw_retrieval_diagnostics, Mapping)
            else {}
        )
        if not generated_in and not evidence_pack_ref:
            return None
        if generated_in != "mcp_sidebar" and not evidence_pack_ref:
            return None
        if not generated_in:
            generated_in = "mcp_sidebar" if evidence_pack_ref else "smart_read"
        raw_qrels_status = retrieval_diagnostics.get("qrels_status")
        message_qrels_status = message.get("qrels_status")
        if isinstance(raw_qrels_status, Mapping):
            qrels_status = dict(raw_qrels_status)
        elif isinstance(message_qrels_status, Mapping):
            qrels_status = dict(message_qrels_status)
        else:
            qrels_status = {}
        raw_gate_status = message.get("evidence_gate_status")
        gate_status = (
            dict(raw_gate_status)
            if isinstance(raw_gate_status, Mapping)
            else {}
        )
        raw_top_evidence_refs = message.get("top_evidence_refs")
        if not isinstance(raw_top_evidence_refs, list):
            raw_top_evidence_refs = message.get("evidence_refs")
        top_evidence_refs = cls._bounded_mapping_items(raw_top_evidence_refs, limit=20)
        visual_observation_refs = sanitize_visual_observation_refs(
            message.get("visual_observation_refs")
        )
        gate_config_hash = ""
        if str(gate_status.get("gate_config_hash") or "").strip():
            gate_config_hash = str(gate_status.get("gate_config_hash") or "").strip()
        else:
            gate_summary = gate_status.get("summary")
            if isinstance(gate_summary, Mapping):
                gate_config_hash = str(gate_summary.get("gate_config_hash") or "").strip()
        fingerprint_inputs = {
            "evidence_pack_ref": evidence_pack_ref,
            "cited_chunk_hashes": sorted(
                str(ref.get("chunk_hash") or ref.get("content_hash") or "")
                for ref in top_evidence_refs
                if str(ref.get("chunk_hash") or ref.get("content_hash") or "").strip()
            ),
            "qrels_content_hash": str(qrels_status.get("qrels_content_hash") or ""),
            "gate_config_hash": gate_config_hash,
            "retrieval_method": str(retrieval_diagnostics.get("retrieval_method") or ""),
            "rerank_status": str(retrieval_diagnostics.get("rerank_status") or ""),
            "fallback_reason": str(retrieval_diagnostics.get("fallback_reason") or "")[:240],
            "visual_observation_hashes": sorted(
                ":".join(
                    part
                    for part in (
                        str(ref.get("candidate_id") or "").strip(),
                        str(ref.get("output_sha256") or "").strip(),
                        str(ref.get("cache_key_hash") or "").strip(),
                    )
                    if part
                )
                for ref in visual_observation_refs
                if str(ref.get("candidate_id") or "").strip()
            ),
        }
        fingerprint_source = json.dumps(
            fingerprint_inputs,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        answer_model = str(
            message.get("answer_model")
            or message.get("answer_model_origin")
            or message.get("model")
            or ""
        ).strip()
        workflow_refs = cls._bounded_json_mapping(message.get("workflow_refs"))
        workflow_passport_ref = cls._bounded_json_mapping(
            message.get("workflow_passport_ref")
            or workflow_refs.get("workflow_passport_ref")
        )
        research_action_lifecycle_ref = cls._bounded_json_mapping(
            message.get("research_action_lifecycle_ref")
            or workflow_refs.get("research_action_lifecycle_ref")
        )
        agent_handoff_card_ref = cls._bounded_json_mapping(
            message.get("agent_handoff_card_ref")
            or workflow_refs.get("agent_handoff_card_ref")
        )
        workflow_replay_lineage_ref = cls._bounded_json_mapping(
            message.get("workflow_replay_lineage_ref")
            or workflow_refs.get("workflow_replay_lineage_ref")
        )
        workflow_replay_index_ref = cls._bounded_json_mapping(
            message.get("workflow_replay_index_ref")
            or workflow_refs.get("workflow_replay_index_ref")
        )
        knowledge_consumer_refs = cls._bounded_json_mapping(message.get("knowledge_consumer_refs"))
        receipt = {
            "receipt_schema_version": ANSWER_RECEIPT_SCHEMA_VERSION,
            "answer_record_schema_version": ANSWER_RECORD_SCHEMA_VERSION,
            "generated_in": generated_in,
            "answer_origin": cls._answer_origin_for_receipt(message.get("answer_origin")),
            "answer_model": answer_model[:120] or None,
            "evidence_origin": "scholar_ai_mcp",
            "output_language": str(message.get("output_language") or session.get("output_language") or "zh")[:20],
            "question": question[:5000],
            "evidence_pack_ref": evidence_pack_ref or None,
            "top_evidence_refs": top_evidence_refs,
            "visual_observation_refs": visual_observation_refs,
            "retrieval_diagnostics": retrieval_diagnostics,
            "qrels_status": qrels_status,
            "evidence_gate_status": gate_status,
            "lifecycle_state": str(message.get("lifecycle_state") or "saved")[:40],
            "staleness_status": "unchecked",
            "receipt_fingerprint": f"sha256:{hashlib.sha256(fingerprint_source.encode('utf-8')).hexdigest()}",
            "receipt_fingerprint_inputs": fingerprint_inputs,
            "updated_at": updated_at,
        }
        if workflow_refs:
            receipt["workflow_refs"] = workflow_refs
        if workflow_passport_ref:
            receipt["workflow_passport_ref"] = workflow_passport_ref
        if research_action_lifecycle_ref:
            receipt["research_action_lifecycle_ref"] = research_action_lifecycle_ref
        if agent_handoff_card_ref:
            receipt["agent_handoff_card_ref"] = agent_handoff_card_ref
        if workflow_replay_lineage_ref:
            receipt["workflow_replay_lineage_ref"] = workflow_replay_lineage_ref
        if workflow_replay_index_ref:
            receipt["workflow_replay_index_ref"] = workflow_replay_index_ref
        if knowledge_consumer_refs:
            receipt["knowledge_consumer_refs"] = knowledge_consumer_refs
        return receipt

    @classmethod
    def _receipt_metadata_from_legacy_session(cls, session: Mapping[str, Any], updated_at: str) -> dict[str, Any] | None:
        messages = session.get("messages")
        if not isinstance(messages, list):
            return None
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if not isinstance(message, Mapping):
                continue
            if str(message.get("role") or "").strip() != "assistant":
                continue
            question = ""
            for previous in range(index - 1, -1, -1):
                previous_message = messages[previous]
                if not isinstance(previous_message, Mapping):
                    continue
                if str(previous_message.get("role") or "").strip() == "user":
                    question = str(previous_message.get("content") or "").strip()
                    break
            receipt = cls._answer_receipt_from_message(
                session=session,
                message=message,
                updated_at=updated_at,
                question=question,
            )
            if receipt is not None:
                return receipt
        return None

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

    def update_conversation_metadata(
        self,
        conversation_id: str,
        metadata: Mapping[str, Any],
        *,
        updated_at: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Merge additive metadata into an existing conversation row."""

        normalized_id = self._require_non_empty_text(conversation_id, "conversation_id")
        safe_metadata = dict(self._coerce_json_mapping(metadata, "metadata"))
        if not safe_metadata:
            return {}
        conn = open_sqlite_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT metadata_json, updated_at FROM conversations WHERE conversation_id = ?",
                (normalized_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"conversation not found: {normalized_id}")
            current = json_loads(row["metadata_json"], default={})
            if not isinstance(current, dict):
                current = {}
            merged = {**current, **safe_metadata}
            effective_updated_at = updated_at or row["updated_at"]
            if isinstance(project_id, str) and project_id.strip():
                conn.execute(
                    """
                    UPDATE conversations
                    SET metadata_json = ?, updated_at = ?, project_id = ?
                    WHERE conversation_id = ?
                    """,
                    (json_dumps(merged), effective_updated_at, project_id.strip(), normalized_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE conversations
                    SET metadata_json = ?, updated_at = ?
                    WHERE conversation_id = ?
                    """,
                    (json_dumps(merged), effective_updated_at, normalized_id),
                )
            conn.commit()
            return merged
        finally:
            conn.close()

    @staticmethod
    def _insert_visual_observations(
        connection: sqlite3.Connection,
        observations: Sequence[VisualObservationCandidate],
        *,
        origin_node_id: str | None,
    ) -> None:
        """Insert validated visual candidates and their source bindings."""

        for observation in observations:
            connection.execute(
                """
                INSERT OR IGNORE INTO visual_observation_candidates (
                    candidate_id, session_id, project_id, turn_id, run_id, observation_order,
                    route, generation_status, review_status, freshness_status, cache_status,
                    cache_key_hash, output_sha256, origin_node_id, created_at,
                    updated_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.candidate_id,
                    observation.session_id,
                    observation.project_id,
                    observation.turn_id,
                    observation.run_id,
                    observation.order,
                    observation.route,
                    observation.generation_status,
                    observation.review_status,
                    observation.freshness_status,
                    observation.cache_status,
                    observation.cache_key_hash,
                    observation.output_sha256,
                    origin_node_id,
                    observation.created_at,
                    observation.updated_at,
                    json_dumps(observation.model_dump(mode="json", exclude_none=True)),
                ),
            )
            for source_fingerprint in observation.source_fingerprints:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO visual_observation_source_bindings (
                        candidate_id, source_fingerprint
                    ) VALUES (?, ?)
                    """,
                    (observation.candidate_id, source_fingerprint),
                )

    def save_visual_observations(
        self,
        observations: Sequence[VisualObservationCandidate],
    ) -> tuple[str, ...]:
        """Persist candidates that do not have a completed answer node.

        Failed provider calls cannot truthfully create an assistant message.
        Their candidates are therefore stored with a nullable origin node while
        retaining the same lifecycle and source-binding contracts.
        """

        if isinstance(observations, (str, bytes)) or not isinstance(observations, Sequence):
            raise TypeError("observations must be a sequence")
        validated: list[VisualObservationCandidate] = []
        for observation in observations:
            if not isinstance(observation, VisualObservationCandidate):
                raise TypeError("observations must contain VisualObservationCandidate values")
            validated.append(observation)
        if not validated:
            return ()

        connection = open_sqlite_connection(self.db_path)
        try:
            self._insert_visual_observations(
                connection,
                validated,
                origin_node_id=None,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return tuple(observation.candidate_id for observation in validated)

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
        safe_raw = dict(self._coerce_json_mapping(raw, "raw"))
        if "turn_id" in safe_raw:
            safe_turn_id = _bounded_optional_text(safe_raw.get("turn_id"), 256)
            if safe_turn_id:
                safe_raw["turn_id"] = safe_turn_id
            else:
                safe_raw.pop("turn_id", None)
        if "research_selections" in safe_raw:
            safe_selections = sanitize_research_selections(safe_raw.get("research_selections"))
            if safe_selections:
                safe_raw["research_selections"] = safe_selections
            else:
                safe_raw.pop("research_selections", None)
        if "visual_observations" in safe_raw:
            safe_observations = sanitize_visual_observations(safe_raw.get("visual_observations"))
            if safe_observations:
                safe_raw["visual_observations"] = safe_observations
            else:
                safe_raw.pop("visual_observations", None)
        if "visual_observation_refs" in safe_raw:
            safe_observation_refs = sanitize_visual_observation_refs(
                safe_raw.get("visual_observation_refs")
            )
            if safe_observation_refs:
                safe_raw["visual_observation_refs"] = safe_observation_refs
            else:
                safe_raw.pop("visual_observation_refs", None)
        elif isinstance(safe_raw.get("visual_observations"), list):
            safe_raw["visual_observation_refs"] = [
                visual_observation_reference(item).model_dump(mode="json", exclude_none=True)
                for item in safe_raw["visual_observations"]
                if isinstance(item, Mapping)
            ]
        raw_json = json_dumps(safe_raw)
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
            self._insert_visual_observations(
                conn,
                [
                    VisualObservationCandidate.model_validate(dict(raw_observation))
                    for raw_observation in safe_raw.get("visual_observations", [])
                    if isinstance(raw_observation, Mapping)
                ],
                origin_node_id=normalized_node_id,
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

        transcript_payload: dict[str, Any] = {
            "node_id": normalized_node_id,
            "parent_node_id": normalized_parent,
            "agent_id": normalized_agent_id,
            "agent_role": normalized_agent_role,
            "run_id": normalized_run_id,
            "role": normalized_role,
            "node_type": normalized_type,
        }
        research_selections = sanitize_research_selections(safe_raw.get("research_selections"))
        turn_id = _bounded_optional_text(safe_raw.get("turn_id"), 256)
        if turn_id:
            transcript_payload["turn_id"] = turn_id
        if research_selections:
            transcript_payload["research_selections"] = research_selections
        visual_observation_refs = sanitize_visual_observation_refs(
            safe_raw.get("visual_observation_refs")
        )
        if visual_observation_refs:
            transcript_payload["visual_observation_refs"] = visual_observation_refs
        self._append_transcript_event(
            conversation_id=normalized_conversation_id,
            event_type="node_appended",
            created_at=normalized_time,
            payload=transcript_payload,
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
        conversation_metadata: dict[str, Any] = {"legacy_imported": True, "updated_at": updated_at}
        answer_receipt = self._receipt_metadata_from_legacy_session(session, updated_at)
        if answer_receipt is not None:
            conversation_metadata.update(
                {
                    "answer_receipt": answer_receipt,
                    "receipt_schema_version": ANSWER_RECEIPT_SCHEMA_VERSION,
                    "answer_record_schema_version": ANSWER_RECORD_SCHEMA_VERSION,
                    "generated_in": answer_receipt.get("generated_in"),
                    "answer_origin": answer_receipt.get("answer_origin"),
                    "evidence_origin": answer_receipt.get("evidence_origin"),
                    "evidence_pack_ref": answer_receipt.get("evidence_pack_ref"),
                    "receipt_fingerprint": answer_receipt.get("receipt_fingerprint"),
                    "lifecycle_state": answer_receipt.get("lifecycle_state"),
                    "staleness_status": answer_receipt.get("staleness_status"),
                    "workflow_passport_ref": answer_receipt.get("workflow_passport_ref"),
                    "workflow_refs": answer_receipt.get("workflow_refs"),
                }
            )
        self.create_conversation(
            conversation_id=session_id,
            created_at=created_at,
            project_id=str(session.get("project_id") or "").strip() or None,
            title=str(session.get("title") or ""),
            mode=str(session.get("mode") or "literature_qa"),
            metadata=conversation_metadata,
        )
        self.update_conversation_metadata(
            session_id,
            conversation_metadata,
            updated_at=updated_at,
            project_id=str(session.get("project_id") or "").strip() or None,
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
            node_id = str(
                message.get("durable_node_id")
                or message.get("id")
                or f"{session_id}_message_{index}"
            )
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
        if archived and archived_at is not None:
            next_archived_at = self._require_non_empty_text(archived_at, "archived_at")
        else:
            next_archived_at = None
        conn = open_sqlite_connection(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT metadata_json FROM conversations WHERE conversation_id = ?",
                (normalized_id,),
            ).fetchone()
            if row is None:
                conn.rollback()
                return False
            metadata = json_loads(row["metadata_json"], default={})
            if (
                not archived
                and isinstance(metadata, Mapping)
                and isinstance(metadata.get("deletion_tombstone"), Mapping)
            ):
                conn.rollback()
                return False
            cursor = conn.execute(
                """
                UPDATE conversations
                SET archived = ?, archived_at = ?
                WHERE conversation_id = ?
                """,
                (1 if archived else 0, next_archived_at, normalized_id),
            )
            conn.commit()
            rowcount = cursor.rowcount
            updated = isinstance(rowcount, int) and rowcount > 0
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
        Tombstone one conversation while retaining its durable audit history.

        Args:
            conversation_id: Existing conversation identifier.
            delete_transcript: Deprecated compatibility argument. Ordinary
                deletion always retains the JSONL transcript; callers that
                genuinely own rollback cleanup must use ``purge_conversation``.

        Returns:
            True when a live conversation was tombstoned. Missing or already
            tombstoned conversations return False.
        """
        normalized_id = self._require_non_empty_text(conversation_id, "conversation_id")
        if not isinstance(delete_transcript, bool):
            raise TypeError("delete_transcript must be a boolean")
        deleted_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        receipt_id = f"conversation-delete:{uuid4().hex}"
        conn = open_sqlite_connection(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT metadata_json FROM conversations WHERE conversation_id = ?",
                (normalized_id,),
            ).fetchone()
            if row is None:
                conn.rollback()
                return False
            metadata = json_loads(row["metadata_json"], default={})
            if not isinstance(metadata, dict):
                metadata = {}
            if isinstance(metadata.get("deletion_tombstone"), Mapping):
                conn.rollback()
                return False
            tombstone = {
                "schema_version": CONVERSATION_TOMBSTONE_SCHEMA_VERSION,
                "receipt_id": receipt_id,
                "deleted_at": deleted_at,
                "retention": "durable_history_retained",
            }
            metadata["deletion_tombstone"] = tombstone
            conn.execute(
                """
                UPDATE conversations
                SET archived = 1,
                    archived_at = ?,
                    updated_at = ?,
                    metadata_json = ?
                WHERE conversation_id = ?
                """,
                (deleted_at, deleted_at, json_dumps(metadata), normalized_id),
            )
            conn.commit()
        finally:
            conn.close()

        self._append_transcript_event(
            conversation_id=normalized_id,
            event_type="conversation_tombstoned",
            created_at=deleted_at,
            payload=tombstone,
        )
        return True

    def purge_conversation(
        self,
        conversation_id: str,
        *,
        confirm_permanent: bool,
        delete_transcript: bool = True,
    ) -> bool:
        """Permanently purge a conversation for owner-controlled rollback cleanup.

        Args:
            conversation_id: Existing conversation identifier.
            confirm_permanent: Must be exactly True to prevent ordinary callers
                from reaching destructive cleanup accidentally.
            delete_transcript: Also remove the JSONL transcript file.

        Returns:
            True when a durable conversation row existed and was purged.

        Raises:
            ValueError: If permanent deletion was not explicitly confirmed.
            TypeError: If either boolean argument has an invalid shape.
        """

        normalized_id = self._require_non_empty_text(conversation_id, "conversation_id")
        if not isinstance(confirm_permanent, bool):
            raise TypeError("confirm_permanent must be a boolean")
        if confirm_permanent is not True:
            raise ValueError("confirm_permanent must be true")
        if not isinstance(delete_transcript, bool):
            raise TypeError("delete_transcript must be a boolean")
        conn = open_sqlite_connection(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            exists = conn.execute(
                "SELECT 1 FROM conversations WHERE conversation_id = ?",
                (normalized_id,),
            ).fetchone()
            if exists is None:
                conn.rollback()
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

    def list_project_conversation_summaries(self, project_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return project-scoped conversation metadata without message content.

        Args:
            project_id: Existing Scholar AI project id stored on conversations.
            limit: Maximum conversation count; must be between 1 and 500.

        Returns:
            Conversation metadata and derived counts. Raw transcript events,
            node ``content_text``, message parts, evidence quotes, and
            compression summaries are intentionally omitted because they may
            contain private local content.
        """

        normalized_project_id = self._require_non_empty_text(project_id, "project_id")
        if not isinstance(limit, int) or limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        conn = open_sqlite_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT
                    c.conversation_id,
                    c.project_id,
                    c.title,
                    c.mode,
                    c.root_node_id,
                    c.head_node_id,
                    c.created_at,
                    c.updated_at,
                    c.archived,
                    c.archived_at,
                    c.metadata_json,
                    (
                        SELECT COUNT(*)
                        FROM conversation_nodes AS n
                        WHERE n.conversation_id = c.conversation_id
                    ) AS node_count,
                    (
                        SELECT COUNT(*)
                        FROM evidence_edges AS e
                        JOIN conversation_nodes AS n ON n.node_id = e.node_id
                        WHERE n.conversation_id = c.conversation_id
                    ) AS evidence_ref_count,
                    (
                        SELECT COUNT(*)
                        FROM conversation_agents AS a
                        WHERE a.conversation_id = c.conversation_id
                    ) AS agent_count,
                    (
                        SELECT COUNT(*)
                        FROM agent_runs AS r
                        WHERE r.conversation_id = c.conversation_id
                    ) AS agent_run_count,
                    (
                        SELECT COUNT(*)
                        FROM compression_snapshots AS s
                        WHERE s.conversation_id = c.conversation_id
                    ) AS compression_snapshot_count
                FROM conversations AS c
                WHERE c.project_id = ?
                ORDER BY c.updated_at DESC, c.conversation_id ASC
                LIMIT ?
                """,
                (normalized_project_id, limit),
            ).fetchall()
            return [
                {
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
                    "node_count": int(row["node_count"] or 0),
                    "evidence_ref_count": int(row["evidence_ref_count"] or 0),
                    "agent_count": int(row["agent_count"] or 0),
                    "agent_run_count": int(row["agent_run_count"] or 0),
                    "compression_snapshot_count": int(row["compression_snapshot_count"] or 0),
                }
                for row in rows
            ]
        finally:
            conn.close()

    def list_conversation_summaries(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """Return recent durable conversation metadata without message content.

        Args:
            limit: Maximum conversation count; must be between 1 and 1000.

        Returns:
            Conversation metadata and derived counts. Raw transcript events,
            node ``content_text``, message parts, evidence quotes, and
            compression summaries are intentionally omitted because they may
            contain private local content.
        """

        if not isinstance(limit, int) or limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        conn = open_sqlite_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT
                    c.conversation_id,
                    c.project_id,
                    c.title,
                    c.mode,
                    c.root_node_id,
                    c.head_node_id,
                    c.created_at,
                    c.updated_at,
                    c.archived,
                    c.archived_at,
                    c.metadata_json,
                    (
                        SELECT COUNT(*)
                        FROM conversation_nodes AS n
                        WHERE n.conversation_id = c.conversation_id
                    ) AS node_count,
                    (
                        SELECT COUNT(*)
                        FROM evidence_edges AS e
                        JOIN conversation_nodes AS n ON n.node_id = e.node_id
                        WHERE n.conversation_id = c.conversation_id
                    ) AS evidence_ref_count,
                    (
                        SELECT COUNT(*)
                        FROM conversation_agents AS a
                        WHERE a.conversation_id = c.conversation_id
                    ) AS agent_count,
                    (
                        SELECT COUNT(*)
                        FROM agent_runs AS r
                        WHERE r.conversation_id = c.conversation_id
                    ) AS agent_run_count,
                    (
                        SELECT COUNT(*)
                        FROM compression_snapshots AS s
                        WHERE s.conversation_id = c.conversation_id
                    ) AS compression_snapshot_count
                FROM conversations AS c
                ORDER BY c.updated_at DESC, c.conversation_id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                {
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
                    "node_count": int(row["node_count"] or 0),
                    "evidence_ref_count": int(row["evidence_ref_count"] or 0),
                    "agent_count": int(row["agent_count"] or 0),
                    "agent_run_count": int(row["agent_run_count"] or 0),
                    "compression_snapshot_count": int(row["compression_snapshot_count"] or 0),
                }
                for row in rows
            ]
        finally:
            conn.close()

    def list_message_nodes(self, conversation_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        """Return recent message nodes for one durable conversation.

        Args:
            conversation_id: Durable SmartRead conversation id.
            limit: Maximum message count; must be between 1 and 500.

        Returns:
            Ordered message nodes with decoded raw and metadata payloads.
        """

        normalized_id = self._require_non_empty_text(conversation_id, "conversation_id")
        if not isinstance(limit, int) or limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        conn = open_sqlite_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT node_id, conversation_id, parent_node_id, agent_id, agent_role, run_id,
                       role, node_type, created_at, content_text, raw_json, metadata_json
                FROM (
                    SELECT rowid AS _rowid, *
                    FROM conversation_nodes
                    WHERE conversation_id = ?
                      AND node_type = 'message'
                    ORDER BY created_at DESC, _rowid DESC
                    LIMIT ?
                )
                ORDER BY created_at ASC, _rowid ASC
                """,
                (normalized_id, limit),
            ).fetchall()
            return [
                {
                    "node_id": row["node_id"],
                    "conversation_id": row["conversation_id"],
                    "parent_node_id": row["parent_node_id"],
                    "agent_id": row["agent_id"],
                    "agent_role": row["agent_role"],
                    "run_id": row["run_id"],
                    "role": row["role"],
                    "node_type": row["node_type"],
                    "created_at": row["created_at"],
                    "content_text": row["content_text"],
                    "raw": json_loads(row["raw_json"], default={}),
                    "metadata": json_loads(row["metadata_json"], default={}),
                }
                for row in rows
            ]
        finally:
            conn.close()

    @staticmethod
    def _visual_observation_from_row(row: sqlite3.Row) -> VisualObservationCandidate:
        """Load one canonical candidate while checking indexed lifecycle columns."""

        try:
            raw = json_loads(row["raw_json"], default={})
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise VisualObservationCorruptionError(
                "visual observation candidate JSON is invalid"
            ) from exc
        if not isinstance(raw, dict):
            raise VisualObservationCorruptionError(
                "visual observation candidate payload is not an object"
            )
        raw["candidate_id"] = str(row["candidate_id"])
        raw["review_status"] = str(row["review_status"])
        raw["freshness_status"] = str(row["freshness_status"])
        raw["updated_at"] = str(row["updated_at"])
        stored_project_id = str(row["project_id"] or "").strip() or None
        raw_project_id = str(raw.get("project_id") or "").strip() or None
        if stored_project_id and raw_project_id and stored_project_id != raw_project_id:
            raise VisualObservationCorruptionError(
                "visual observation project identity drifted"
            )
        if stored_project_id is not None:
            raw["project_id"] = stored_project_id
        try:
            return VisualObservationCandidate.model_validate(raw)
        except (TypeError, ValueError) as exc:
            raise VisualObservationCorruptionError(
                "visual observation candidate failed validation"
            ) from exc

    @classmethod
    def _get_visual_observation_in_connection(
        cls,
        connection: sqlite3.Connection,
        candidate_id: str,
    ) -> VisualObservationCandidate | None:
        row = connection.execute(
            """
            SELECT candidate_id, project_id, review_status, freshness_status,
                   updated_at, raw_json
            FROM visual_observation_candidates
            WHERE candidate_id = ?
            """,
            (candidate_id,),
        ).fetchone()
        return None if row is None else cls._visual_observation_from_row(row)

    def get_visual_observation(self, candidate_id: str) -> dict[str, Any] | None:
        """Return one validated visual observation candidate by id.

        Args:
            candidate_id: Stable candidate identifier stored with a chat turn.

        Returns:
            Pixel-free candidate data, or ``None`` when the id is unknown.

        Raises:
            VisualObservationCorruptionError: If a stored row is inconsistent.
        """

        normalized_id = _visual_identifier(candidate_id, "candidate_id")
        conn = open_sqlite_connection(self.db_path)
        try:
            candidate = self._get_visual_observation_in_connection(conn, normalized_id)
            return (
                None
                if candidate is None
                else candidate.model_dump(mode="json", exclude_none=True)
            )
        finally:
            conn.close()

    def list_visual_observations(
        self,
        session_id: str,
        *,
        turn_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List visual observations recorded for one session in stable order."""

        normalized_session = _visual_identifier(session_id, "session_id")
        if not isinstance(limit, int) or limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        normalized_turn = turn_id.strip() if isinstance(turn_id, str) and turn_id.strip() else None
        conn = open_sqlite_connection(self.db_path)
        try:
            if normalized_turn is None:
                rows = conn.execute(
                    """
                    SELECT candidate_id
                    FROM visual_observation_candidates
                    WHERE session_id = ?
                    ORDER BY created_at ASC, run_id ASC, observation_order ASC
                    LIMIT ?
                    """,
                    (normalized_session, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT candidate_id
                    FROM visual_observation_candidates
                    WHERE session_id = ? AND turn_id = ?
                    ORDER BY created_at ASC, run_id ASC, observation_order ASC
                    LIMIT ?
                    """,
                    (normalized_session, normalized_turn, limit),
                ).fetchall()
            observations: list[dict[str, Any]] = []
            for row in rows:
                candidate = self._get_visual_observation_in_connection(
                    conn,
                    str(row["candidate_id"]),
                )
                observation = (
                    None
                    if candidate is None
                    else candidate.model_dump(mode="json", exclude_none=True)
                )
                if observation is not None:
                    observations.append(observation)
            return observations
        finally:
            conn.close()

    @classmethod
    def _load_visual_observation_replay(
        cls,
        connection: sqlite3.Connection,
        *,
        candidate_id: str,
        operation_id: str,
        request_sha256: str,
    ) -> VisualObservationMutationResult | None:
        row = connection.execute(
            """
            SELECT candidate_id, event_id, request_sha256, raw_json,
                   candidate_raw_json
            FROM visual_observation_lifecycle_receipts
            WHERE operation_id = ?
            """,
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        if str(row["candidate_id"]) != candidate_id:
            raise VisualObservationConflictError(
                "operation_id was already used for another visual candidate"
            )
        if str(row["request_sha256"]) != request_sha256:
            raise VisualObservationConflictError(
                "operation_id was already used for a different lifecycle request"
            )
        event_row = connection.execute(
            """
            SELECT raw_json
            FROM visual_observation_lifecycle_events
            WHERE event_id = ?
            """,
            (str(row["event_id"]),),
        ).fetchone()
        if event_row is None:
            raise VisualObservationCorruptionError(
                "visual lifecycle receipt event is missing"
            )
        try:
            receipt = VisualObservationLifecycleReceipt.model_validate_json(
                str(row["raw_json"])
            )
            event = VisualObservationLifecycleEvent.model_validate_json(
                str(event_row["raw_json"])
            )
            candidate = VisualObservationCandidate.model_validate_json(
                str(row["candidate_raw_json"])
            )
        except (TypeError, ValueError) as exc:
            raise VisualObservationCorruptionError(
                "visual lifecycle replay payload is invalid"
            ) from exc
        if (
            receipt.event_id != event.event_id
            or receipt.operation_id != event.operation_id
            or receipt.candidate_id != event.candidate_id
            or receipt.session_id != event.session_id
            or receipt.project_id != event.project_id
            or receipt.axis != event.axis
            or receipt.from_status != event.from_status
            or receipt.to_status != event.to_status
            or receipt.previous_review_status != event.previous_review_status
            or receipt.previous_freshness_status != event.previous_freshness_status
            or receipt.result_review_status != event.result_review_status
            or receipt.result_freshness_status != event.result_freshness_status
            or receipt.reason != event.reason
            or receipt.changed_by != event.changed_by
            or receipt.occurred_at != event.occurred_at
            or candidate.candidate_id != receipt.candidate_id
            or candidate.session_id != receipt.session_id
            or candidate.project_id != receipt.project_id
            or candidate.review_status != receipt.result_review_status
            or candidate.freshness_status != receipt.result_freshness_status
            or _visual_datetime(candidate.updated_at, "candidate.updated_at")
            != receipt.occurred_at
        ):
            raise VisualObservationCorruptionError(
                "visual lifecycle replay payloads disagree"
            )
        return VisualObservationMutationResult(
            candidate=candidate,
            event=event,
            receipt=receipt,
            replayed=True,
        )

    def transition_visual_observation(
        self,
        candidate_id: str,
        *,
        request: VisualObservationLifecycleRequest,
        occurred_at: datetime | None = None,
    ) -> VisualObservationMutationResult:
        """Atomically commit one dual-axis CAS transition, event, and receipt.

        Args:
            candidate_id: Candidate bound by the route or caller.
            request: Strict expected-state, target, actor, reason, and operation id.
            occurred_at: Optional aware test/audit timestamp; runtime callers omit it.

        Returns:
            The committed candidate snapshot, event, receipt, and replay flag.

        Raises:
            KeyError: If the candidate does not exist.
            VisualObservationConflictError: If CAS or idempotency does not match.
            VisualObservationStoreError: If the atomic mutation cannot be stored.

        Notes:
            This ledger has no path to Wiki, qrels, evidence gates, or accepted
            graph facts. Review acceptance only changes this candidate record.
        """

        normalized_id = _visual_identifier(candidate_id, "candidate_id")
        if not isinstance(request, VisualObservationLifecycleRequest):
            raise TypeError("request must be VisualObservationLifecycleRequest")
        request_hash = visual_observation_lifecycle_request_hash(request)
        conn = open_sqlite_connection(self.db_path)
        committed: VisualObservationMutationResult | None = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            replay = self._load_visual_observation_replay(
                conn,
                candidate_id=normalized_id,
                operation_id=request.operation_id,
                request_sha256=request_hash,
            )
            if replay is not None:
                conn.commit()
                return replay
            current = self._get_visual_observation_in_connection(conn, normalized_id)
            if current is None:
                raise KeyError(normalized_id)
            if (
                current.review_status != request.expected_review_status
                or current.freshness_status != request.expected_freshness_status
            ):
                raise VisualObservationConflictError(
                    "visual observation lifecycle state changed after it was read"
                )

            axis: VisualObservationLifecycleAxis
            from_status: VisualObservationLifecycleStatus
            to_status: VisualObservationLifecycleStatus
            next_review_status: VisualObservationReviewStatus
            next_freshness_status: VisualObservationFreshnessStatus
            if request.target_review_status is not None:
                verdict = evaluate_visual_observation_transition(
                    generation_status=current.generation_status,
                    current=current.review_status,
                    target=request.target_review_status,
                )
                axis = "review"
                from_status = current.review_status
                to_status = request.target_review_status
                next_review_status = request.target_review_status
                next_freshness_status = current.freshness_status
            else:
                if request.target_freshness_status is None:
                    raise RuntimeError("freshness target disappeared during validation")
                verdict = evaluate_visual_observation_freshness_transition(
                    current=current.freshness_status,
                    target=request.target_freshness_status,
                )
                axis = "freshness"
                from_status = current.freshness_status
                to_status = request.target_freshness_status
                next_review_status = current.review_status
                next_freshness_status = request.target_freshness_status
            if not verdict.allowed or verdict.no_op:
                raise VisualObservationConflictError(verdict.reason)

            transition_time = _next_visual_timestamp(
                current.updated_at,
                requested=occurred_at,
            )
            timestamp = _visual_timestamp(transition_time)
            candidate_payload = current.model_dump(mode="python")
            candidate_payload["review_status"] = next_review_status
            candidate_payload["freshness_status"] = next_freshness_status
            candidate_payload["updated_at"] = timestamp
            candidate = VisualObservationCandidate.model_validate(candidate_payload)
            event = VisualObservationLifecycleEvent(
                event_id=f"visual-event-{uuid4().hex}",
                operation_id=request.operation_id,
                candidate_id=candidate.candidate_id,
                session_id=candidate.session_id,
                project_id=candidate.project_id,
                axis=axis,
                from_status=from_status,
                to_status=to_status,
                previous_review_status=current.review_status,
                previous_freshness_status=current.freshness_status,
                result_review_status=candidate.review_status,
                result_freshness_status=candidate.freshness_status,
                reason=request.reason,
                changed_by=request.changed_by,
                occurred_at=transition_time,
            )
            receipt = VisualObservationLifecycleReceipt(
                receipt_id=f"visual-receipt-{uuid4().hex}",
                operation_id=request.operation_id,
                request_sha256=request_hash,
                event_id=event.event_id,
                candidate_id=candidate.candidate_id,
                session_id=candidate.session_id,
                project_id=candidate.project_id,
                axis=event.axis,
                from_status=event.from_status,
                to_status=event.to_status,
                previous_review_status=event.previous_review_status,
                previous_freshness_status=event.previous_freshness_status,
                result_review_status=event.result_review_status,
                result_freshness_status=event.result_freshness_status,
                reason=event.reason,
                changed_by=event.changed_by,
                occurred_at=event.occurred_at,
            )
            update = conn.execute(
                """
                UPDATE visual_observation_candidates
                SET review_status = ?, freshness_status = ?, updated_at = ?, raw_json = ?
                WHERE candidate_id = ?
                  AND review_status = ?
                  AND freshness_status = ?
                  AND updated_at = ?
                """,
                (
                    candidate.review_status,
                    candidate.freshness_status,
                    candidate.updated_at,
                    json_dumps(candidate.model_dump(mode="json", exclude_none=True)),
                    normalized_id,
                    current.review_status,
                    current.freshness_status,
                    current.updated_at,
                ),
            )
            if update.rowcount != 1:
                raise VisualObservationConflictError(
                    "visual observation lifecycle state changed during commit"
                )
            conn.execute(
                """
                INSERT INTO visual_observation_lifecycle_events (
                    event_id, operation_id, candidate_id, session_id, project_id,
                    axis, from_status, to_status, occurred_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.operation_id,
                    event.candidate_id,
                    event.session_id,
                    event.project_id,
                    event.axis,
                    event.from_status,
                    event.to_status,
                    timestamp,
                    event.model_dump_json(exclude_none=False),
                ),
            )
            conn.execute(
                """
                INSERT INTO visual_observation_lifecycle_receipts (
                    operation_id, receipt_id, event_id, candidate_id, session_id,
                    project_id, request_sha256, occurred_at, raw_json,
                    candidate_raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.operation_id,
                    receipt.receipt_id,
                    receipt.event_id,
                    receipt.candidate_id,
                    receipt.session_id,
                    receipt.project_id,
                    receipt.request_sha256,
                    timestamp,
                    receipt.model_dump_json(exclude_none=False),
                    candidate.model_dump_json(exclude_none=False),
                ),
            )
            conn.commit()
            committed = VisualObservationMutationResult(
                candidate=candidate,
                event=event,
                receipt=receipt,
                replayed=False,
            )
        except (KeyError, ValueError, VisualObservationStoreError):
            conn.rollback()
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise VisualObservationStoreError(
                "visual observation lifecycle transaction failed"
            ) from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        if committed is None:
            raise RuntimeError("visual observation transaction completed without a result")
        self._append_transcript_event(
            conversation_id=committed.candidate.session_id,
            event_type="visual_observation_lifecycle_changed",
            created_at=_visual_timestamp(committed.event.occurred_at),
            payload=committed.event.model_dump(mode="json", exclude_none=True),
        )
        return committed

    @staticmethod
    def _source_revision_pending_in_connection(
        connection: sqlite3.Connection,
        *,
        candidate_id: str,
        source_revision: VisualObservationSourceRevisionIdentity,
    ) -> bool:
        row = connection.execute(
            """
            SELECT raw_json
            FROM visual_observation_lifecycle_events
            WHERE candidate_id = ? AND axis = 'freshness'
            ORDER BY occurred_at DESC, event_id DESC
            LIMIT 1
            """,
            (candidate_id,),
        ).fetchone()
        if row is None:
            return False
        try:
            event = VisualObservationLifecycleEvent.model_validate_json(
                str(row["raw_json"])
            )
        except (TypeError, ValueError) as exc:
            raise VisualObservationCorruptionError(
                "visual source revision event is invalid"
            ) from exc
        return (
            event.axis == "freshness"
            and event.to_status == "stale"
            and event.source_revision_operation == "mark_stale"
            and event.source_revision == source_revision
        )

    @classmethod
    def _preflight_visual_source_revision_in_connection(
        cls,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        operation: VisualObservationSourceRevisionOperation,
        source_revision: VisualObservationSourceRevisionIdentity,
    ) -> VisualObservationSourceRevisionPreflight:
        if operation not in {"mark_stale", "revalidate"}:
            raise ValueError(f"unsupported visual source revision operation: {operation!r}")
        expected_freshness = "fresh" if operation == "mark_stale" else "stale"
        rows = connection.execute(
            """
            SELECT candidate.candidate_id, candidate.project_id,
                   candidate.review_status, candidate.freshness_status,
                   candidate.updated_at, candidate.raw_json
            FROM visual_observation_candidates AS candidate
            JOIN visual_observation_source_bindings AS source
              ON source.candidate_id = candidate.candidate_id
            WHERE candidate.project_id = ?
              AND candidate.freshness_status = ?
              AND source.source_fingerprint = ?
            ORDER BY candidate.candidate_id ASC
            LIMIT ?
            """,
            (
                project_id,
                expected_freshness,
                source_revision.previous_source_fingerprint,
                _VISUAL_SOURCE_REVISION_MAX_IMPACTS + 1,
            ),
        ).fetchall()
        if len(rows) > _VISUAL_SOURCE_REVISION_MAX_IMPACTS:
            raise VisualObservationConflictError(
                "visual source revision impact exceeds the bounded apply limit"
            )
        impacts: list[VisualObservationSourceRevisionImpact] = []
        for row in rows:
            candidate = cls._visual_observation_from_row(row)
            if candidate.project_id != project_id:
                raise VisualObservationCorruptionError(
                    "visual source revision candidate project drifted"
                )
            if operation == "revalidate" and not cls._source_revision_pending_in_connection(
                connection,
                candidate_id=candidate.candidate_id,
                source_revision=source_revision,
            ):
                continue
            impacts.append(
                VisualObservationSourceRevisionImpact(
                    candidate_id=candidate.candidate_id,
                    expected_review_status=candidate.review_status,
                    expected_freshness_status=candidate.freshness_status,
                    expected_updated_at=_visual_datetime(
                        candidate.updated_at,
                        "candidate.updated_at",
                    ),
                )
            )
        impact_tuple = tuple(impacts)
        impact_fingerprint = visual_observation_source_revision_impact_fingerprint(
            project_id=project_id,
            operation=operation,
            source_revision=source_revision,
            impacts=impact_tuple,
        )
        return VisualObservationSourceRevisionPreflight(
            project_id=project_id,
            operation=operation,
            source_revision=source_revision,
            impacts=impact_tuple,
            impact_fingerprint=impact_fingerprint,
        )

    def preflight_visual_observation_source_revision(
        self,
        *,
        project_id: str,
        operation: VisualObservationSourceRevisionOperation,
        source_revision: VisualObservationSourceRevisionIdentity,
    ) -> VisualObservationSourceRevisionPreflight:
        """Return a read-only, complete project-scoped source impact set.

        Args:
            project_id: Project that owns all eligible candidates.
            operation: Whether to mark matching fresh candidates stale or
                revalidate candidates previously staled by this exact revision.
            source_revision: Exact previous and current source fingerprints.

        Returns:
            Sorted impacts and their deterministic apply fingerprint.
        """

        normalized_project = _visual_identifier(project_id, "project_id")
        if not isinstance(source_revision, VisualObservationSourceRevisionIdentity):
            raise TypeError("source_revision must be VisualObservationSourceRevisionIdentity")
        conn = open_sqlite_connection(self.db_path)
        try:
            return self._preflight_visual_source_revision_in_connection(
                conn,
                project_id=normalized_project,
                operation=operation,
                source_revision=source_revision,
            )
        finally:
            conn.close()

    @staticmethod
    def _load_visual_source_revision_replay(
        connection: sqlite3.Connection,
        *,
        request: VisualObservationSourceRevisionApplyRequest,
        request_sha256: str,
    ) -> VisualObservationSourceRevisionResult | None:
        row = connection.execute(
            """
            SELECT project_id, operation, request_sha256, raw_json
            FROM visual_observation_source_revision_receipts
            WHERE operation_id = ?
            """,
            (request.operation_id,),
        ).fetchone()
        if row is None:
            return None
        if (
            str(row["project_id"]) != request.project_id
            or str(row["operation"]) != request.operation
            or str(row["request_sha256"]) != request_sha256
        ):
            raise VisualObservationConflictError(
                "operation_id was already used for a different source revision request"
            )
        try:
            receipt = VisualObservationSourceRevisionApplyReceipt.model_validate_json(
                str(row["raw_json"])
            )
        except (TypeError, ValueError) as exc:
            raise VisualObservationCorruptionError(
                "visual source revision receipt is invalid"
            ) from exc
        for expected_event in receipt.events:
            event_row = connection.execute(
                """
                SELECT raw_json
                FROM visual_observation_lifecycle_events
                WHERE event_id = ?
                """,
                (expected_event.event_id,),
            ).fetchone()
            if event_row is None:
                raise VisualObservationCorruptionError(
                    "visual source revision receipt event is missing"
                )
            try:
                stored_event = VisualObservationLifecycleEvent.model_validate_json(
                    str(event_row["raw_json"])
                )
            except (TypeError, ValueError) as exc:
                raise VisualObservationCorruptionError(
                    "visual source revision event is invalid"
                ) from exc
            if stored_event != expected_event:
                raise VisualObservationCorruptionError(
                    "visual source revision receipt and event disagree"
                )
        return VisualObservationSourceRevisionResult(receipt=receipt, replayed=True)

    def apply_visual_observation_source_revision(
        self,
        request: VisualObservationSourceRevisionApplyRequest,
        *,
        occurred_at: datetime | None = None,
    ) -> VisualObservationSourceRevisionResult:
        """Atomically apply one exact source-revision preflight impact set.

        Args:
            request: Idempotency, project, source identity, exact impact digest,
                confirmed candidate ids, reason, and actor.
            occurred_at: Optional aware test/audit timestamp; runtime callers omit it.

        Returns:
            Aggregate durable receipt and replay flag.

        Raises:
            VisualObservationConflictError: If impact or candidate CAS changed.
            VisualObservationStoreError: If no all-or-nothing commit is possible.
        """

        if not isinstance(request, VisualObservationSourceRevisionApplyRequest):
            raise TypeError("request must be VisualObservationSourceRevisionApplyRequest")
        request_hash = visual_observation_source_revision_request_hash(request)
        conn = open_sqlite_connection(self.db_path)
        committed: VisualObservationSourceRevisionResult | None = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            replay = self._load_visual_source_revision_replay(
                conn,
                request=request,
                request_sha256=request_hash,
            )
            if replay is not None:
                conn.commit()
                return replay
            preflight = self._preflight_visual_source_revision_in_connection(
                conn,
                project_id=request.project_id,
                operation=request.operation,
                source_revision=request.source_revision,
            )
            if preflight.impact_fingerprint != request.expected_impact_fingerprint:
                raise VisualObservationConflictError(
                    "visual source revision impact changed after preflight"
                )
            impacted_ids = tuple(impact.candidate_id for impact in preflight.impacts)
            if not impacted_ids:
                raise VisualObservationConflictError(
                    f"no visual candidates require {request.operation}"
                )
            if impacted_ids != request.validated_candidate_ids:
                raise VisualObservationConflictError(
                    "validated_candidate_ids do not match the complete current impact"
                )
            transition_time = _next_visual_timestamp(
                *(
                    _visual_timestamp(impact.expected_updated_at)
                    for impact in preflight.impacts
                ),
                requested=occurred_at,
            )
            timestamp = _visual_timestamp(transition_time)
            target_freshness: VisualObservationFreshnessStatus = (
                "stale" if request.operation == "mark_stale" else "fresh"
            )
            receipt_id = f"visual-source-receipt-{uuid4().hex}"
            events: list[VisualObservationLifecycleEvent] = []
            for impact in preflight.impacts:
                current = self._get_visual_observation_in_connection(
                    conn,
                    impact.candidate_id,
                )
                if current is None:
                    raise VisualObservationConflictError(
                        "visual source revision candidate disappeared during apply"
                    )
                if (
                    current.project_id != request.project_id
                    or current.review_status != impact.expected_review_status
                    or current.freshness_status != impact.expected_freshness_status
                    or _visual_datetime(current.updated_at, "candidate.updated_at")
                    != impact.expected_updated_at
                ):
                    raise VisualObservationConflictError(
                        "visual source revision candidate changed during apply"
                    )
                verdict = evaluate_visual_observation_freshness_transition(
                    current=current.freshness_status,
                    target=target_freshness,
                )
                if not verdict.allowed or verdict.no_op:
                    raise VisualObservationConflictError(verdict.reason)
                candidate_payload = current.model_dump(mode="python")
                candidate_payload["freshness_status"] = target_freshness
                candidate_payload["updated_at"] = timestamp
                updated = VisualObservationCandidate.model_validate(candidate_payload)
                event = VisualObservationLifecycleEvent(
                    event_id=f"visual-event-{uuid4().hex}",
                    operation_id=request.operation_id,
                    candidate_id=updated.candidate_id,
                    session_id=updated.session_id,
                    project_id=updated.project_id,
                    axis="freshness",
                    from_status=current.freshness_status,
                    to_status=updated.freshness_status,
                    previous_review_status=current.review_status,
                    previous_freshness_status=current.freshness_status,
                    result_review_status=updated.review_status,
                    result_freshness_status=updated.freshness_status,
                    reason=request.reason,
                    changed_by=request.changed_by,
                    occurred_at=transition_time,
                    source_revision_receipt_id=receipt_id,
                    source_revision_operation=request.operation,
                    source_revision=request.source_revision,
                    source_revision_impact_fingerprint=preflight.impact_fingerprint,
                )
                update = conn.execute(
                    """
                    UPDATE visual_observation_candidates
                    SET freshness_status = ?, updated_at = ?, raw_json = ?
                    WHERE candidate_id = ?
                      AND project_id = ?
                      AND review_status = ?
                      AND freshness_status = ?
                      AND updated_at = ?
                    """,
                    (
                        updated.freshness_status,
                        updated.updated_at,
                        json_dumps(updated.model_dump(mode="json", exclude_none=True)),
                        updated.candidate_id,
                        request.project_id,
                        impact.expected_review_status,
                        impact.expected_freshness_status,
                        current.updated_at,
                    ),
                )
                if update.rowcount != 1:
                    raise VisualObservationConflictError(
                        "visual source revision candidate changed during commit"
                    )
                if request.operation == "revalidate":
                    binding_delete = conn.execute(
                        """
                        DELETE FROM visual_observation_source_bindings
                        WHERE candidate_id = ? AND source_fingerprint = ?
                        """,
                        (
                            updated.candidate_id,
                            request.source_revision.previous_source_fingerprint,
                        ),
                    )
                    if binding_delete.rowcount != 1:
                        raise VisualObservationConflictError(
                            "visual source binding changed during revalidation"
                        )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO visual_observation_source_bindings (
                            candidate_id, source_fingerprint
                        ) VALUES (?, ?)
                        """,
                        (
                            updated.candidate_id,
                            request.source_revision.current_source_fingerprint,
                        ),
                    )
                conn.execute(
                    """
                    INSERT INTO visual_observation_lifecycle_events (
                        event_id, operation_id, candidate_id, session_id, project_id,
                        axis, from_status, to_status, occurred_at, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.operation_id,
                        event.candidate_id,
                        event.session_id,
                        event.project_id,
                        event.axis,
                        event.from_status,
                        event.to_status,
                        timestamp,
                        event.model_dump_json(exclude_none=False),
                    ),
                )
                events.append(event)
            receipt = VisualObservationSourceRevisionApplyReceipt(
                receipt_id=receipt_id,
                operation_id=request.operation_id,
                request_sha256=request_hash,
                project_id=request.project_id,
                operation=request.operation,
                source_revision=request.source_revision,
                impact_fingerprint=preflight.impact_fingerprint,
                candidate_ids=impacted_ids,
                events=tuple(events),
                reason=request.reason,
                changed_by=request.changed_by,
                occurred_at=transition_time,
            )
            conn.execute(
                """
                INSERT INTO visual_observation_source_revision_receipts (
                    operation_id, receipt_id, project_id, operation,
                    request_sha256, impact_fingerprint, occurred_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.operation_id,
                    receipt.receipt_id,
                    receipt.project_id,
                    receipt.operation,
                    receipt.request_sha256,
                    receipt.impact_fingerprint,
                    timestamp,
                    receipt.model_dump_json(exclude_none=False),
                ),
            )
            conn.commit()
            committed = VisualObservationSourceRevisionResult(
                receipt=receipt,
                replayed=False,
            )
        except (ValueError, VisualObservationStoreError):
            conn.rollback()
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise VisualObservationStoreError(
                "visual source revision transaction failed"
            ) from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        if committed is None:
            raise RuntimeError("visual source revision completed without a result")
        for event in committed.receipt.events:
            self._append_transcript_event(
                conversation_id=event.session_id,
                event_type="visual_observation_lifecycle_changed",
                created_at=_visual_timestamp(event.occurred_at),
                payload=event.model_dump(mode="json", exclude_none=True),
            )
        return committed

    def get_visual_observation_lifecycle_receipt(
        self,
        operation_id: str,
    ) -> VisualObservationLifecycleReceipt | None:
        """Read one durable explicit-transition receipt by operation id."""

        normalized_operation = _visual_identifier(operation_id, "operation_id")
        conn = open_sqlite_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT raw_json
                FROM visual_observation_lifecycle_receipts
                WHERE operation_id = ?
                """,
                (normalized_operation,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        try:
            return VisualObservationLifecycleReceipt.model_validate_json(
                str(row["raw_json"])
            )
        except (TypeError, ValueError) as exc:
            raise VisualObservationCorruptionError(
                "visual lifecycle receipt is invalid"
            ) from exc

    def get_visual_observation_source_revision_receipt(
        self,
        operation_id: str,
    ) -> VisualObservationSourceRevisionApplyReceipt | None:
        """Read one durable aggregate source-revision receipt by operation id."""

        normalized_operation = _visual_identifier(operation_id, "operation_id")
        conn = open_sqlite_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT raw_json
                FROM visual_observation_source_revision_receipts
                WHERE operation_id = ?
                """,
                (normalized_operation,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        try:
            return VisualObservationSourceRevisionApplyReceipt.model_validate_json(
                str(row["raw_json"])
            )
        except (TypeError, ValueError) as exc:
            raise VisualObservationCorruptionError(
                "visual source revision receipt is invalid"
            ) from exc

    def list_visual_observation_lifecycle_events(
        self,
        *,
        candidate_id: str | None = None,
        operation_id: str | None = None,
        limit: int = 100,
    ) -> tuple[VisualObservationLifecycleEvent, ...]:
        """Return a bounded lifecycle event page in stable commit order."""

        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        where: list[str] = []
        parameters: list[object] = []
        if candidate_id is not None:
            where.append("candidate_id = ?")
            parameters.append(_visual_identifier(candidate_id, "candidate_id"))
        if operation_id is not None:
            where.append("operation_id = ?")
            parameters.append(_visual_identifier(operation_id, "operation_id"))
        query = "SELECT raw_json FROM visual_observation_lifecycle_events"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY occurred_at ASC, event_id ASC LIMIT ?"
        parameters.append(limit)
        conn = open_sqlite_connection(self.db_path)
        try:
            rows = conn.execute(query, tuple(parameters)).fetchall()
        finally:
            conn.close()
        try:
            return tuple(
                VisualObservationLifecycleEvent.model_validate_json(str(row["raw_json"]))
                for row in rows
            )
        except (TypeError, ValueError) as exc:
            raise VisualObservationCorruptionError(
                "visual lifecycle event is invalid"
            ) from exc

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

    def get_latest_message(self, conversation_id: str, *, role: NodeRole = "assistant") -> dict[str, Any] | None:
        """Return the latest message node for a conversation and role.

        Args:
            conversation_id: Durable SmartRead conversation id.
            role: Message role to load. Only conversation-node roles are
                accepted so callers cannot turn this into an arbitrary query.

        Returns:
            A decoded message node with bounded metadata and content text, or
            ``None`` when no matching message exists.

        Raises:
            ValueError: If ``conversation_id`` or ``role`` is empty/unsupported.
        """

        normalized_id = self._require_non_empty_text(conversation_id, "conversation_id")
        normalized_role = self._require_non_empty_text(role, "role")
        if normalized_role not in {"user", "assistant", "system", "tool"}:
            raise ValueError(f"unsupported role: {normalized_role}")
        conn = open_sqlite_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT node_id, conversation_id, parent_node_id, agent_id, agent_role, run_id,
                       role, node_type, created_at, content_text, raw_json, metadata_json
                FROM conversation_nodes
                WHERE conversation_id = ?
                  AND role = ?
                  AND node_type = 'message'
                ORDER BY created_at DESC, node_id DESC
                LIMIT 1
                """,
                (normalized_id, normalized_role),
            ).fetchone()
            if row is None:
                return None
            return {
                "node_id": row["node_id"],
                "conversation_id": row["conversation_id"],
                "parent_node_id": row["parent_node_id"],
                "agent_id": row["agent_id"],
                "agent_role": row["agent_role"],
                "run_id": row["run_id"],
                "role": row["role"],
                "node_type": row["node_type"],
                "created_at": row["created_at"],
                "content_text": row["content_text"],
                "raw": json_loads(row["raw_json"], default={}),
                "metadata": json_loads(row["metadata_json"], default={}),
            }
        finally:
            conn.close()
