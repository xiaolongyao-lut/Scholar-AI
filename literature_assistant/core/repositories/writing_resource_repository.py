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


RESOURCE_STATE_KEYS = (
    "projects",
    "sections",
    "materials",
    "figure_assets",
    "drafts",
    "revisions",
    "draft_revisions",
)


def _clone_resource_section(state: Mapping[str, Any], key: str) -> dict[str, dict[str, Any]]:
    raw_value = state.get(key, {})
    if not isinstance(raw_value, Mapping):
        raise TypeError(f"serialized writing resource state section {key!r} must be a mapping")

    cloned: dict[str, dict[str, Any]] = {}
    for item_id, payload in raw_value.items():
        if not isinstance(payload, Mapping):
            raise TypeError(f"serialized writing resource state item {key}.{item_id!s} must be a mapping")
        cloned[str(item_id)] = dict(payload)
    return cloned


def _required_text(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if value in (None, ""):
        raise TypeError(f"serialized writing resource item must include non-empty {field_name!r}")
    return str(value)


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def normalize_writing_resource_state(state: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """
    Return a persistence-safe writing resource snapshot and repair notes.

    Args:
        state: Serialized store snapshot with project/resource mappings.

    Returns:
        A normalized snapshot plus human-readable repair notes. The snapshot
        preserves valid resources and applies SQLite-equivalent reference
        semantics before full-state replacement.
    """
    if not isinstance(state, Mapping):
        raise TypeError("state must be a mapping")

    projects = _clone_resource_section(state, "projects")
    sections = _clone_resource_section(state, "sections")
    materials = _clone_resource_section(state, "materials")
    figure_assets = _clone_resource_section(state, "figure_assets")
    drafts = _clone_resource_section(state, "drafts")
    revisions = _clone_resource_section(state, "revisions")

    raw_draft_revisions = state.get("draft_revisions", {})
    if not isinstance(raw_draft_revisions, Mapping):
        raise TypeError("serialized writing resource state section 'draft_revisions' must be a mapping")

    repairs: list[str] = []
    project_ids = {_required_text(payload, "project_id") for payload in projects.values()}

    def keep_project_scoped(
        items: dict[str, dict[str, Any]],
        *,
        kind: str,
    ) -> dict[str, dict[str, Any]]:
        kept: dict[str, dict[str, Any]] = {}
        for key, payload in items.items():
            project_id = _required_text(payload, "project_id")
            if project_id not in project_ids:
                repairs.append(f"dropped {kind} {key}: missing project {project_id}")
                continue
            kept[key] = payload
        return kept

    sections = keep_project_scoped(sections, kind="section")
    materials = keep_project_scoped(materials, kind="material")
    material_ids = {_required_text(payload, "material_id") for payload in materials.values()}

    kept_figure_assets: dict[str, dict[str, Any]] = {}
    for key, payload in figure_assets.items():
        project_id = _required_text(payload, "project_id")
        if project_id not in project_ids:
            repairs.append(f"dropped figure asset {key}: missing project {project_id}")
            continue
        material_id = _optional_text(payload.get("material_id"))
        if material_id is not None and material_id not in material_ids:
            payload = dict(payload)
            payload["material_id"] = None
            repairs.append(f"cleared figure asset {key} material link: missing material {material_id}")
        kept_figure_assets[key] = payload
    figure_assets = kept_figure_assets

    section_ids = {_required_text(payload, "section_id") for payload in sections.values()}
    kept_drafts: dict[str, dict[str, Any]] = {}
    for key, payload in drafts.items():
        project_id = _required_text(payload, "project_id")
        if project_id not in project_ids:
            repairs.append(f"dropped draft {key}: missing project {project_id}")
            continue
        section_id = _optional_text(payload.get("section_id"))
        if section_id is not None and section_id not in section_ids:
            payload = dict(payload)
            payload["section_id"] = None
            repairs.append(f"cleared draft {key} section link: missing section {section_id}")
        kept_drafts[key] = payload
    drafts = kept_drafts

    draft_project_ids = {
        _required_text(payload, "draft_id"): _required_text(payload, "project_id")
        for payload in drafts.values()
    }
    kept_revisions: dict[str, dict[str, Any]] = {}
    for key, payload in revisions.items():
        draft_id = _required_text(payload, "draft_id")
        draft_project_id = draft_project_ids.get(draft_id)
        if draft_project_id is None:
            repairs.append(f"dropped revision {key}: missing draft {draft_id}")
            continue
        project_id = _required_text(payload, "project_id")
        if project_id != draft_project_id:
            payload = dict(payload)
            payload["project_id"] = draft_project_id
            repairs.append(f"repaired revision {key} project link: {project_id} -> {draft_project_id}")
        kept_revisions[key] = payload
    revisions = kept_revisions

    revision_draft_ids = {
        _required_text(payload, "revision_id"): _required_text(payload, "draft_id")
        for payload in revisions.values()
    }
    normalized_draft_revisions: dict[str, list[str]] = {}
    for draft_id_raw, revision_ids_raw in raw_draft_revisions.items():
        draft_id = str(draft_id_raw)
        if draft_id not in draft_project_ids:
            repairs.append(f"dropped revision links for missing draft {draft_id}")
            continue
        if not isinstance(revision_ids_raw, Sequence) or isinstance(revision_ids_raw, (str, bytes)):
            raise TypeError("draft_revisions entries must be sequences")
        normalized_revision_ids: list[str] = []
        for revision_id_raw in revision_ids_raw:
            revision_id = str(revision_id_raw)
            linked_draft_id = revision_draft_ids.get(revision_id)
            if linked_draft_id is None:
                repairs.append(f"dropped draft {draft_id} link to missing revision {revision_id}")
                continue
            if linked_draft_id != draft_id:
                repairs.append(f"dropped draft {draft_id} link to revision {revision_id}: belongs to {linked_draft_id}")
                continue
            normalized_revision_ids.append(revision_id)
        normalized_draft_revisions[draft_id] = normalized_revision_ids

    normalized = dict(state)
    normalized.update(
        {
            "projects": projects,
            "sections": sections,
            "materials": materials,
            "figure_assets": figure_assets,
            "drafts": drafts,
            "revisions": revisions,
            "draft_revisions": normalized_draft_revisions,
        }
    )
    return normalized, repairs


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
                CREATE TABLE IF NOT EXISTS figure_assets (
                    asset_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    caption TEXT NOT NULL,
                    numbering TEXT NOT NULL,
                    material_id TEXT,
                    source_page INTEGER,
                    bbox TEXT,
                    asset_path TEXT NOT NULL,
                    width INTEGER,
                    height INTEGER,
                    format TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_figure_assets_project_id ON figure_assets(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_figure_assets_material_id ON figure_assets(material_id)")
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
        state, _repairs = normalize_writing_resource_state(state)
        conn = open_sqlite_connection(self.db_path)
        try:
            conn.execute("BEGIN")
            for table in (
                "draft_revision_links",
                "revisions",
                "drafts",
                "figure_assets",
                "materials",
                "sections",
                "projects",
            ):
                conn.execute(f"DELETE FROM {table}")

            projects = state.get("projects", {})
            sections = state.get("sections", {})
            materials = state.get("materials", {})
            figure_assets = state.get("figure_assets", {})
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
                INSERT INTO figure_assets (
                    asset_id, project_id, kind, caption, numbering, material_id,
                    source_page, bbox, asset_path, width, height, format,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(payload["asset_id"]),
                        str(payload["project_id"]),
                        str(payload["kind"]),
                        str(payload["caption"]),
                        str(payload["numbering"]),
                        None if payload.get("material_id") in (None, "") else str(payload.get("material_id")),
                        payload.get("source_page"),
                        json_dumps(payload.get("bbox")) if payload.get("bbox") is not None else None,
                        str(payload.get("asset_path")),
                        payload.get("width"),
                        payload.get("height"),
                        None if payload.get("format") in (None, "") else str(payload.get("format")),
                        str(payload.get("created_at")),
                        str(payload.get("updated_at")),
                    )
                    for payload in figure_assets.values()
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

            figure_assets = {
                str(row["asset_id"]): {
                    "asset_id": row["asset_id"],
                    "project_id": row["project_id"],
                    "kind": row["kind"],
                    "caption": row["caption"],
                    "numbering": row["numbering"],
                    "material_id": row["material_id"],
                    "source_page": row["source_page"],
                    "bbox": json_loads(row["bbox"], default=None) if row["bbox"] is not None else None,
                    "asset_path": row["asset_path"],
                    "width": row["width"],
                    "height": row["height"],
                    "format": row["format"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for row in conn.execute("SELECT * FROM figure_assets ORDER BY created_at DESC, asset_id ASC")
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
                "figure_assets": figure_assets,
                "drafts": drafts,
                "revisions": revisions,
                "draft_revisions": dict(draft_revisions),
            }
        finally:
            conn.close()

    def is_empty(self) -> bool:
        """Return True when the repository has no resource rows yet."""
        return not self.has_data()
