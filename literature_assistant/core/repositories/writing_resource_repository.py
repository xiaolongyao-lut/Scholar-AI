# -*- coding: utf-8 -*-
"""SQLite repository for writing resources."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

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


class WritingResourceRepository:
    """Durable SQLite storage for projects, sections, materials, drafts, and revisions."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser().resolve()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        conn = open_sqlite_connection(self.db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    user_id TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    tags TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sections (
                    section_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    ord INTEGER NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS materials (
                    material_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    title_en TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    summary_en TEXT NOT NULL DEFAULT '',
                    type TEXT NOT NULL DEFAULT 'reference',
                    focus_points TEXT NOT NULL DEFAULT '[]',
                    focus_points_en TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS drafts (
                    draft_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    section_id TEXT,
                    title TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_edited_by TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE,
                    FOREIGN KEY(section_id) REFERENCES sections(section_id) ON DELETE SET NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS revisions (
                    revision_id TEXT PRIMARY KEY,
                    draft_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    revision_number INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT,
                    message TEXT NOT NULL DEFAULT 'Auto-saved',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(draft_id) REFERENCES drafts(draft_id) ON DELETE CASCADE,
                    FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS draft_revision_links (
                    draft_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    revision_id TEXT NOT NULL,
                    PRIMARY KEY(draft_id, position),
                    FOREIGN KEY(draft_id) REFERENCES drafts(draft_id) ON DELETE CASCADE,
                    FOREIGN KEY(revision_id) REFERENCES revisions(revision_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sections_project_id ON sections(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_materials_project_id ON materials(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_drafts_project_id ON drafts(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_drafts_section_id ON drafts(section_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_revisions_draft_id ON revisions(draft_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_revisions_project_id ON revisions(project_id)")
            conn.commit()
        finally:
            conn.close()

    def has_data(self) -> bool:
        """Return True when any project rows already exist."""
        conn = open_sqlite_connection(self.db_path)
        try:
            row = conn.execute("SELECT 1 FROM projects LIMIT 1").fetchone()
            return row is not None
        finally:
            conn.close()

    def get_health_report(self) -> dict[str, Any]:
        """Return a combined health report for the resource database."""
        return collect_sqlite_health_report(self.db_path)

    def is_healthy(self) -> bool:
        """Return True when the resource database passes integrity checks."""
        return bool(self.get_health_report()["ok"])

    def get_stats(self) -> dict[str, Any]:
        """Return low-level file and pragma statistics for the resource database."""
        return get_sqlite_database_stats(self.db_path)

    def checkpoint_wal(self, mode: str = "PASSIVE") -> dict[str, Any]:
        """Checkpoint the resource database WAL."""
        return checkpoint_sqlite_wal(self.db_path, mode=mode)

    def vacuum(self) -> dict[str, Any]:
        """Run VACUUM / optimize against the resource database."""
        return vacuum_sqlite_database(self.db_path)

    def backup_to(self, backup_path: str | Path) -> Path:
        """Create a backup copy of the resource database."""
        return backup_sqlite_database(self.db_path, backup_path)

    def restore_from(self, backup_path: str | Path) -> Path:
        """Restore the resource database from a backup copy."""
        return restore_sqlite_database(backup_path, self.db_path)

    def replace_state(self, state: Mapping[str, Any]) -> None:
        """Replace the full repository state from serialized resource data."""
        conn = open_sqlite_connection(self.db_path)
        try:
            conn.execute("BEGIN")
            for table in (
                "draft_revision_links",
                "revisions",
                "drafts",
                "materials",
                "sections",
                "projects",
            ):
                conn.execute(f"DELETE FROM {table}")

            projects = state.get("projects", {})
            sections = state.get("sections", {})
            materials = state.get("materials", {})
            drafts = state.get("drafts", {})
            revisions = state.get("revisions", {})
            draft_revisions = state.get("draft_revisions", {})

            conn.executemany(
                """
                INSERT INTO projects (
                    project_id, title, description, status, content_type, created_at,
                    updated_at, user_id, metadata, tags
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(payload["project_id"]),
                        str(payload["title"]),
                        str(payload.get("description", "")),
                        str(payload.get("status", "draft")),
                        str(payload.get("content_type", "general")),
                        str(payload.get("created_at")),
                        str(payload.get("updated_at")),
                        None if payload.get("user_id") in (None, "") else str(payload.get("user_id")),
                        json_dumps(payload.get("metadata") or {}),
                        json_dumps(list(payload.get("tags", []))),
                    )
                    for payload in projects.values()
                ],
            )

            conn.executemany(
                """
                INSERT INTO sections (
                    section_id, project_id, title, ord, description, created_at,
                    updated_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(payload["section_id"]),
                        str(payload["project_id"]),
                        str(payload["title"]),
                        int(payload["order"]),
                        str(payload.get("description", "")),
                        str(payload.get("created_at")),
                        str(payload.get("updated_at")),
                        json_dumps(payload.get("metadata") or {}),
                    )
                    for payload in sections.values()
                ],
            )

            conn.executemany(
                """
                INSERT INTO materials (
                    material_id, project_id, title, title_en, summary, summary_en, type,
                    focus_points, focus_points_en, created_at, updated_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(payload["material_id"]),
                        str(payload["project_id"]),
                        str(payload["title"]),
                        str(payload.get("title_en", "")),
                        str(payload.get("summary", "")),
                        str(payload.get("summary_en", "")),
                        str(payload.get("type", "reference") or "reference"),
                        json_dumps(list(payload.get("focus_points", []))),
                        json_dumps(list(payload.get("focus_points_en", []))),
                        str(payload.get("created_at")),
                        str(payload.get("updated_at")),
                        json_dumps(payload.get("metadata") or {}),
                    )
                    for payload in materials.values()
                ],
            )

            conn.executemany(
                """
                INSERT INTO drafts (
                    draft_id, project_id, section_id, title, content, status, created_at,
                    updated_at, last_edited_by, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(payload["draft_id"]),
                        str(payload["project_id"]),
                        None if payload.get("section_id") in (None, "") else str(payload.get("section_id")),
                        str(payload.get("title", "")),
                        str(payload.get("content", "")),
                        str(payload.get("status", "created")),
                        str(payload.get("created_at")),
                        str(payload.get("updated_at")),
                        None if payload.get("last_edited_by") in (None, "") else str(payload.get("last_edited_by")),
                        json_dumps(payload.get("metadata") or {}),
                    )
                    for payload in drafts.values()
                ],
            )

            conn.executemany(
                """
                INSERT INTO revisions (
                    revision_id, draft_id, project_id, content, revision_number, created_at,
                    created_by, message, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(payload["revision_id"]),
                        str(payload["draft_id"]),
                        str(payload["project_id"]),
                        str(payload.get("content", "")),
                        int(payload.get("revision_number", 1)),
                        str(payload.get("created_at")),
                        None if payload.get("created_by") in (None, "") else str(payload.get("created_by")),
                        str(payload.get("message", "Auto-saved")),
                        json_dumps(payload.get("metadata") or {}),
                    )
                    for payload in revisions.values()
                ],
            )

            link_rows: list[tuple[str, int, str]] = []
            for draft_id, revision_ids in draft_revisions.items():
                if not isinstance(revision_ids, Sequence) or isinstance(revision_ids, (str, bytes)):
                    raise TypeError("draft_revisions entries must be sequences")
                for position, revision_id in enumerate(revision_ids):
                    link_rows.append((str(draft_id), position, str(revision_id)))
            conn.executemany(
                """
                INSERT INTO draft_revision_links (draft_id, position, revision_id)
                VALUES (?, ?, ?)
                """,
                link_rows,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def load_state(self) -> dict[str, Any]:
        """Load the full repository state as the same snapshot shape used by the store."""
        conn = open_sqlite_connection(self.db_path)
        try:
            projects = {
                str(row["project_id"]): {
                    "project_id": row["project_id"],
                    "title": row["title"],
                    "description": row["description"],
                    "status": row["status"],
                    "content_type": row["content_type"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "user_id": row["user_id"],
                    "metadata": json_loads(row["metadata"], default={}),
                    "tags": json_loads(row["tags"], default=[]),
                }
                for row in conn.execute("SELECT * FROM projects ORDER BY created_at ASC, project_id ASC")
            }

            sections = {
                str(row["section_id"]): {
                    "section_id": row["section_id"],
                    "project_id": row["project_id"],
                    "title": row["title"],
                    "order": row["ord"],
                    "description": row["description"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "metadata": json_loads(row["metadata"], default={}),
                }
                for row in conn.execute("SELECT * FROM sections ORDER BY project_id ASC, ord ASC, section_id ASC")
            }

            materials = {
                str(row["material_id"]): {
                    "material_id": row["material_id"],
                    "project_id": row["project_id"],
                    "title": row["title"],
                    "title_en": row["title_en"],
                    "summary": row["summary"],
                    "summary_en": row["summary_en"],
                    "type": row["type"],
                    "focus_points": json_loads(row["focus_points"], default=[]),
                    "focus_points_en": json_loads(row["focus_points_en"], default=[]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "metadata": json_loads(row["metadata"], default={}),
                }
                for row in conn.execute("SELECT * FROM materials ORDER BY created_at DESC, material_id ASC")
            }

            drafts = {
                str(row["draft_id"]): {
                    "draft_id": row["draft_id"],
                    "project_id": row["project_id"],
                    "section_id": row["section_id"],
                    "title": row["title"],
                    "content": row["content"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "last_edited_by": row["last_edited_by"],
                    "metadata": json_loads(row["metadata"], default={}),
                }
                for row in conn.execute("SELECT * FROM drafts ORDER BY created_at DESC, draft_id ASC")
            }

            revisions = {
                str(row["revision_id"]): {
                    "revision_id": row["revision_id"],
                    "draft_id": row["draft_id"],
                    "project_id": row["project_id"],
                    "content": row["content"],
                    "revision_number": row["revision_number"],
                    "created_at": row["created_at"],
                    "created_by": row["created_by"],
                    "message": row["message"],
                    "metadata": json_loads(row["metadata"], default={}),
                }
                for row in conn.execute("SELECT * FROM revisions ORDER BY draft_id ASC, revision_number ASC, revision_id ASC")
            }

            draft_revisions: dict[str, list[str]] = defaultdict(list)
            for row in conn.execute(
                "SELECT draft_id, revision_id FROM draft_revision_links ORDER BY draft_id ASC, position ASC"
            ):
                draft_revisions[str(row["draft_id"])].append(str(row["revision_id"]))

            return {
                "projects": projects,
                "sections": sections,
                "materials": materials,
                "drafts": drafts,
                "revisions": revisions,
                "draft_revisions": dict(draft_revisions),
            }
        finally:
            conn.close()

    def is_empty(self) -> bool:
        """Return True when the repository has no resource rows yet."""
        return not self.has_data()
