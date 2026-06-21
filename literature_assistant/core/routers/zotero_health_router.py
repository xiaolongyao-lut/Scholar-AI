"""Read-only Zotero attachment health diagnostics for Scholar AI."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from models import ToolAttempt, ToolNextAction, ToolOutcome
from project_paths import WORKSPACE_OUTPUT_ROOT, ensure_directory


ZOTERO_ATTACHMENT_HEALTH_SCHEMA_VERSION = "scholar-ai-zotero-attachment-health/v1"
AttachmentHealthStatus = Literal[
    "ok",
    "missing_attachment_row",
    "missing_file",
    "linked_file_outside_allowed_root",
    "non_pdf_attachment",
    "zero_or_short_extracted_text",
    "duplicate_doi",
]
HealthAggregateStatus = Literal["ok", "degraded", "blocked"]

_DEFAULT_MIN_TEXT_CHARS = 200
_ZOTERO_LINK_MODE_LINKED_FILE = 2

router = APIRouter(prefix="/api/zotero", tags=["Zotero"])


class ZoteroAttachmentItem(BaseModel):
    """One bounded Zotero attachment diagnostic row.

    Args:
        item_key: Zotero parent item key.
        title: Optional parent item title.
        doi: Optional parent DOI.
        attachment_key: Optional Zotero attachment item key.
        status: Closed health status for deterministic filters.
        reason: Short non-secret explanation.
        details: Small JSON-safe metadata without full local file content.
    """

    item_key: str = Field(default="", max_length=64)
    title: str = Field(default="", max_length=300)
    doi: str = Field(default="", max_length=180)
    attachment_key: str = Field(default="", max_length=64)
    status: AttachmentHealthStatus
    reason: str = Field(default="", max_length=500)
    details: dict[str, Any] = Field(default_factory=dict)


class ZoteroAttachmentHealthResponse(BaseModel):
    """Versioned read-only Zotero attachment health report.

    Args:
        schema_version: Stable response contract.
        status: Aggregate result across inspected rows.
        generated_at: UTC timestamp.
        zotero_data_dir: Source Zotero data directory.
        snapshot_used: Whether the SQLite database was copied before reading.
        summary: Counts and report metadata.
        items: Bounded diagnostic rows.
        reports: Local artifact paths under workspace output.
        outcome: ToolOutcome envelope for MCP and UI consumers.
    """

    schema_version: Literal["scholar-ai-zotero-attachment-health/v1"] = ZOTERO_ATTACHMENT_HEALTH_SCHEMA_VERSION
    status: HealthAggregateStatus
    generated_at: str
    zotero_data_dir: str
    snapshot_used: bool
    summary: dict[str, Any] = Field(default_factory=dict)
    items: list[ZoteroAttachmentItem] = Field(default_factory=list)
    reports: dict[str, str] = Field(default_factory=dict)
    outcome: ToolOutcome


class _RawAttachmentRow(BaseModel):
    """Internal typed row assembled from Zotero SQLite tables."""

    parent_item_id: int
    item_key: str
    title: str = ""
    doi: str = ""
    attachment_item_id: int | None = None
    attachment_key: str = ""
    link_mode: int | None = None
    content_type: str = ""
    raw_path: str = ""
    indexed_chars: int | None = None
    total_chars: int | None = None


def _now_iso_z() -> str:
    """Return a second-resolution UTC timestamp for reports."""

    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clean_optional_path(value: str | None, field_name: str) -> Path | None:
    """Resolve optional user-supplied local paths defensively."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    cleaned = value.strip().strip('"')
    if not cleaned:
        return None
    return Path(cleaned).expanduser().resolve()


def _resolve_data_dir(zotero_data_dir: str | None) -> Path:
    """Resolve a Zotero data directory and reject missing database files."""

    path = _clean_optional_path(zotero_data_dir, "zotero_data_dir")
    if path is None:
        raise ValueError("zotero_data_dir is required")
    if path.is_file() and path.name == "zotero.sqlite":
        path = path.parent
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError("Zotero data directory does not exist")
    db_path = path / "zotero.sqlite"
    if not db_path.exists() or not db_path.is_file():
        raise FileNotFoundError("zotero.sqlite was not found in the Zotero data directory")
    return path


def _table_names(conn: sqlite3.Connection) -> set[str]:
    """Return SQLite table names for schema-version tolerant queries."""

    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {str(row[0]) for row in cursor.fetchall()}


def _field_ids(conn: sqlite3.Connection, field_name: str, tables: set[str]) -> list[int]:
    """Return Zotero field ids from fieldsCombined or fields."""

    ids: list[int] = []
    for table in ("fieldsCombined", "fields"):
        if table not in tables:
            continue
        cursor = conn.execute(f"SELECT fieldID FROM {table} WHERE fieldName = ?", (field_name,))
        ids.extend(int(row[0]) for row in cursor.fetchall())
    return sorted(set(ids))


def _field_values(conn: sqlite3.Connection, field_ids: list[int]) -> dict[int, str]:
    """Return itemID to first non-empty field value for the supplied field ids."""

    if not field_ids:
        return {}
    placeholders = ",".join("?" for _ in field_ids)
    query = (
        "SELECT itemData.itemID, itemDataValues.value "
        "FROM itemData JOIN itemDataValues ON itemDataValues.valueID = itemData.valueID "
        f"WHERE itemData.fieldID IN ({placeholders})"
    )
    values: dict[int, str] = {}
    for item_id, value in conn.execute(query, tuple(field_ids)).fetchall():
        text = str(value or "").strip()
        if text and int(item_id) not in values:
            values[int(item_id)] = text
    return values


def _load_fulltext_chars(conn: sqlite3.Connection, tables: set[str]) -> dict[int, tuple[int | None, int | None]]:
    """Return indexed and total char counts when Zotero full-text metadata exists."""

    if "fulltextItems" not in tables:
        return {}
    cursor = conn.execute("PRAGMA table_info(fulltextItems)")
    columns = {str(row[1]) for row in cursor.fetchall()}
    if "itemID" not in columns:
        return {}
    indexed_expr = "indexedChars" if "indexedChars" in columns else "NULL"
    total_expr = "totalChars" if "totalChars" in columns else "NULL"
    query = f"SELECT itemID, {indexed_expr}, {total_expr} FROM fulltextItems"
    result: dict[int, tuple[int | None, int | None]] = {}
    for item_id, indexed, total in conn.execute(query).fetchall():
        result[int(item_id)] = (
            int(indexed) if indexed is not None else None,
            int(total) if total is not None else None,
        )
    return result


def _load_zotero_rows(snapshot_db_path: Path) -> list[_RawAttachmentRow]:
    """Read Zotero item and attachment metadata from a copied database."""

    conn = sqlite3.connect(f"file:{snapshot_db_path.as_posix()}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        tables = _table_names(conn)
        if "items" not in tables or "itemAttachments" not in tables:
            raise sqlite3.DatabaseError("Zotero database is missing required item tables")

        title_values = _field_values(conn, _field_ids(conn, "title", tables))
        doi_values = _field_values(conn, _field_ids(conn, "DOI", tables))
        fulltext = _load_fulltext_chars(conn, tables)
        deleted_ids: set[int] = set()
        if "deletedItems" in tables:
            deleted_ids = {int(row[0]) for row in conn.execute("SELECT itemID FROM deletedItems").fetchall()}

        item_keys: dict[int, str] = {
            int(row["itemID"]): str(row["key"] or "").strip().upper()
            for row in conn.execute("SELECT itemID, key FROM items").fetchall()
            if int(row["itemID"]) not in deleted_ids
        }
        attachment_item_ids: set[int] = set()
        attachments_by_parent: dict[int, list[sqlite3.Row]] = defaultdict(list)
        for row in conn.execute(
            "SELECT itemID, parentItemID, linkMode, contentType, path FROM itemAttachments"
        ).fetchall():
            attachment_item_id = int(row["itemID"])
            attachment_item_ids.add(attachment_item_id)
            if attachment_item_id in deleted_ids:
                continue
            parent_id = row["parentItemID"]
            if parent_id is None or int(parent_id) in deleted_ids:
                continue
            attachments_by_parent[int(parent_id)].append(row)

        rows: list[_RawAttachmentRow] = []
        parent_ids = [
            item_id
            for item_id in sorted(item_keys)
            if item_id not in attachment_item_ids
            and (item_id in title_values or item_id in doi_values or item_id in attachments_by_parent)
        ]
        for parent_id in parent_ids:
            attachments = attachments_by_parent.get(parent_id) or [None]
            for attachment in attachments:
                attachment_id = int(attachment["itemID"]) if attachment is not None else None
                indexed_chars = None
                total_chars = None
                if attachment_id is not None and attachment_id in fulltext:
                    indexed_chars, total_chars = fulltext[attachment_id]
                rows.append(
                    _RawAttachmentRow(
                        parent_item_id=parent_id,
                        item_key=item_keys.get(parent_id, ""),
                        title=title_values.get(parent_id, ""),
                        doi=doi_values.get(parent_id, ""),
                        attachment_item_id=attachment_id,
                        attachment_key=item_keys.get(attachment_id, "") if attachment_id is not None else "",
                        link_mode=int(attachment["linkMode"]) if attachment is not None and attachment["linkMode"] is not None else None,
                        content_type=str(attachment["contentType"] or "") if attachment is not None else "",
                        raw_path=str(attachment["path"] or "") if attachment is not None else "",
                        indexed_chars=indexed_chars,
                        total_chars=total_chars,
                    )
                )
        return rows
    finally:
        conn.close()


def _normalize_doi(value: str) -> str:
    """Return a stable DOI key for duplicate detection."""

    cleaned = str(value or "").strip().lower()
    cleaned = cleaned.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    cleaned = cleaned.removeprefix("doi:")
    return cleaned.strip()


def _is_relative_to(path: Path, root: Path) -> bool:
    """Return whether path is under root without relying on Python minor versions."""

    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _resolve_attachment_path(data_dir: Path, row: _RawAttachmentRow) -> Path | None:
    """Resolve Zotero storage and linked-file attachment paths."""

    raw_path = row.raw_path.strip()
    if not row.attachment_key or not raw_path:
        return None
    if raw_path.startswith("storage:"):
        suffix = raw_path.split(":", 1)[1].lstrip("/\\")
        return (data_dir / "storage" / row.attachment_key / suffix).resolve()
    if raw_path.startswith("attachments:"):
        suffix = raw_path.split(":", 1)[1].lstrip("/\\")
        return (data_dir / "storage" / row.attachment_key / suffix).resolve()
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    if row.link_mode == _ZOTERO_LINK_MODE_LINKED_FILE:
        return (data_dir / raw_path).resolve()
    return (data_dir / "storage" / row.attachment_key / raw_path).resolve()


def _attachment_status(
    data_dir: Path,
    allowed_root: Path,
    row: _RawAttachmentRow,
    duplicate_dois: set[str],
    min_text_chars: int,
) -> tuple[AttachmentHealthStatus, str, dict[str, Any]]:
    """Classify one attachment row using read-only filesystem checks."""

    details: dict[str, Any] = {
        "parent_item_id": row.parent_item_id,
        "attachment_item_id": row.attachment_item_id,
        "content_type": row.content_type,
        "link_mode": row.link_mode,
        "raw_path_kind": "empty" if not row.raw_path else row.raw_path.split(":", 1)[0] if ":" in row.raw_path else "path",
        "indexed_chars": row.indexed_chars,
        "total_chars": row.total_chars,
    }
    normalized_doi = _normalize_doi(row.doi)
    if row.attachment_item_id is None:
        return "missing_attachment_row", "No Zotero attachment row is linked to this bibliographic item.", details

    resolved_path = _resolve_attachment_path(data_dir, row)
    details["resolved_path_exists"] = bool(resolved_path and resolved_path.exists())
    details["resolved_path_suffix"] = resolved_path.suffix.lower() if resolved_path is not None else ""
    if row.link_mode == _ZOTERO_LINK_MODE_LINKED_FILE and resolved_path is not None:
        details["inside_allowed_root"] = _is_relative_to(resolved_path, allowed_root)
        if not details["inside_allowed_root"]:
            return (
                "linked_file_outside_allowed_root",
                "Linked attachment resolves outside the allowed local root.",
                details,
            )
    if resolved_path is None or not resolved_path.exists() or not resolved_path.is_file():
        return "missing_file", "Attachment file could not be found on disk.", details

    is_pdf = row.content_type.lower() == "application/pdf" or resolved_path.suffix.lower() == ".pdf"
    if not is_pdf:
        return "non_pdf_attachment", "Attachment is not a PDF and cannot satisfy PDF-first ingestion readiness.", details

    observed_chars = max(row.indexed_chars or 0, row.total_chars or 0)
    if observed_chars < min_text_chars:
        return (
            "zero_or_short_extracted_text",
            "Zotero full-text metadata is missing or too short for reliable paper reading.",
            details,
        )

    if normalized_doi and normalized_doi in duplicate_dois:
        details["duplicate_doi"] = normalized_doi
        return "duplicate_doi", "The same DOI appears on multiple Zotero parent items.", details

    return "ok", "Attachment exists, is PDF-like, and has enough indexed text metadata.", details


def _item_from_row(
    data_dir: Path,
    allowed_root: Path,
    row: _RawAttachmentRow,
    duplicate_dois: set[str],
    min_text_chars: int,
) -> ZoteroAttachmentItem:
    """Build one public diagnostic item."""

    status, reason, details = _attachment_status(
        data_dir=data_dir,
        allowed_root=allowed_root,
        row=row,
        duplicate_dois=duplicate_dois,
        min_text_chars=min_text_chars,
    )
    return ZoteroAttachmentItem(
        item_key=row.item_key,
        title=row.title[:300],
        doi=row.doi[:180],
        attachment_key=row.attachment_key,
        status=status,
        reason=reason,
        details=details,
    )


def _aggregate_status(items: list[ZoteroAttachmentItem]) -> HealthAggregateStatus:
    """Aggregate item-level statuses into probe-style readiness."""

    if not items:
        return "blocked"
    if all(item.status == "ok" for item in items):
        return "ok"
    return "degraded"


def _safe_report_stem(data_dir: Path) -> str:
    """Return a stable non-secret report stem from the data directory."""

    digest = hashlib.sha256(str(data_dir).encode("utf-8")).hexdigest()[:10]
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"zotero-attachment-health-{stamp}-{digest}"


def _write_reports(response: ZoteroAttachmentHealthResponse, data_dir: Path) -> dict[str, str]:
    """Write JSON and Markdown reports under workspace output."""

    output_dir = ensure_directory(WORKSPACE_OUTPUT_ROOT / "zotero-health")
    stem = _safe_report_stem(data_dir)
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(response.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Zotero Attachment Health",
        "",
        f"- Status: {response.status}",
        f"- Generated at: {response.generated_at}",
        f"- Inspected items: {response.summary.get('inspected_item_count', 0)}",
        f"- Attachment rows: {response.summary.get('attachment_row_count', 0)}",
        "",
        "## Status Counts",
        "",
    ]
    for status, count in sorted(dict(response.summary.get("status_counts") or {}).items()):
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Attention Needed", ""])
    attention = [item for item in response.items if item.status != "ok"]
    if not attention:
        lines.append("- None")
    for item in attention[:200]:
        label = item.title or item.doi or item.item_key or "untitled"
        lines.append(f"- `{item.status}` {label}: {item.reason}")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def _blocked_response(data_dir_label: str, reason: str, error_class: str) -> ZoteroAttachmentHealthResponse:
    """Return an actionable blocked response for invalid local Zotero state."""

    next_action = ToolNextAction(
        kind="open_settings",
        message="Provide a Zotero data directory containing zotero.sqlite, then rerun the health check.",
    )
    outcome = ToolOutcome(
        status="config_needed",
        quality="none",
        reason=reason,
        next_action=next_action,
        attempts=[
            ToolAttempt(
                stage="zotero_preflight",
                status="blocked",
                reason=reason,
                error_class=error_class,
                recommendation=next_action.message,
            )
        ],
    )
    return ZoteroAttachmentHealthResponse(
        status="blocked",
        generated_at=_now_iso_z(),
        zotero_data_dir=data_dir_label,
        snapshot_used=False,
        summary={"status_counts": {}, "error_class": error_class},
        outcome=outcome,
    )


def build_zotero_attachment_health_response(
    zotero_data_dir: str | None,
    *,
    allowed_root: str | None = None,
    min_text_chars: int = _DEFAULT_MIN_TEXT_CHARS,
    max_items: int = 500,
    write_reports: bool = True,
) -> ZoteroAttachmentHealthResponse:
    """Build a read-only Zotero attachment health response.

    Args:
        zotero_data_dir: Zotero data directory or direct zotero.sqlite path.
        allowed_root: Root under which linked files are considered local and
            permitted. Defaults to the Zotero data directory.
        min_text_chars: Minimum Zotero full-text character count for readiness.
        max_items: Maximum public item rows returned in the API response.
        write_reports: Whether to write JSON and Markdown reports to output.

    Returns:
        Versioned health diagnostics. The original Zotero SQLite database is
        never opened for mutation; reads use a temporary copied snapshot.
    """

    if not isinstance(min_text_chars, int) or isinstance(min_text_chars, bool) or min_text_chars < 0:
        raise ValueError("min_text_chars must be a non-negative integer")
    if not isinstance(max_items, int) or isinstance(max_items, bool) or max_items < 1 or max_items > 5000:
        raise ValueError("max_items must be between 1 and 5000")

    try:
        data_dir = _resolve_data_dir(zotero_data_dir)
        allowed_root_path = _clean_optional_path(allowed_root, "allowed_root") or data_dir
    except (FileNotFoundError, ValueError) as exc:
        return _blocked_response(str(zotero_data_dir or ""), str(exc), exc.__class__.__name__)

    source_db_path = data_dir / "zotero.sqlite"
    with tempfile.TemporaryDirectory(prefix="scholar-ai-zotero-") as temp_dir:
        snapshot_path = Path(temp_dir) / "zotero.snapshot.sqlite"
        shutil.copy2(source_db_path, snapshot_path)
        rows = _load_zotero_rows(snapshot_path)

    doi_counts = Counter(_normalize_doi(row.doi) for row in rows if _normalize_doi(row.doi))
    duplicate_dois = {doi for doi, count in doi_counts.items() if count > 1}
    all_items = [
        _item_from_row(
            data_dir=data_dir,
            allowed_root=allowed_root_path,
            row=row,
            duplicate_dois=duplicate_dois,
            min_text_chars=min_text_chars,
        )
        for row in rows
    ]
    status_counts = Counter(item.status for item in all_items)
    status = _aggregate_status(all_items)
    public_items = all_items[:max_items]
    recommendations = [
        ToolNextAction(
            kind="obtain_full_text",
            message="Open the listed Zotero items and restore or relink missing local PDF attachments manually.",
        )
    ] if status != "ok" else []
    attempts = [
        ToolAttempt(
            stage="zotero_snapshot",
            status="success",
            reason="Copied zotero.sqlite to a temporary snapshot before reading.",
            metadata={"source_db_bytes": source_db_path.stat().st_size},
        ),
        ToolAttempt(
            stage="attachment_health",
            status="success" if status == "ok" else "degraded",
            reason="Inspected Zotero attachment rows without writing repair state.",
            metadata={"status_counts": dict(status_counts), "duplicate_doi_count": len(duplicate_dois)},
        ),
    ]
    outcome = ToolOutcome(
        status="success" if status == "ok" else "degraded",
        quality="full" if status == "ok" else "partial",
        reason=(
            "Zotero attachment health checks passed."
            if status == "ok"
            else "Zotero attachment health is degraded; inspect status counts and report artifacts."
        ),
        next_action=recommendations[0] if recommendations else ToolNextAction(kind="none", message=""),
        attempts=attempts,
    )
    response = ZoteroAttachmentHealthResponse(
        status=status,
        generated_at=_now_iso_z(),
        zotero_data_dir=str(data_dir),
        snapshot_used=True,
        summary={
            "inspected_item_count": len({row.parent_item_id for row in rows}),
            "attachment_row_count": sum(1 for row in rows if row.attachment_item_id is not None),
            "returned_item_count": len(public_items),
            "truncated": len(all_items) > len(public_items),
            "status_counts": dict(status_counts),
            "duplicate_doi_count": len(duplicate_dois),
            "min_text_chars": min_text_chars,
            "allowed_root": str(allowed_root_path),
        },
        items=public_items,
        reports={},
        outcome=outcome,
    )
    if write_reports:
        response.reports = _write_reports(response, data_dir)
    return response


@router.get("/attachment-health", response_model=ZoteroAttachmentHealthResponse)
async def get_zotero_attachment_health(
    zotero_data_dir: str | None = Query(default=None),
    allowed_root: str | None = Query(default=None),
    min_text_chars: int = Query(default=_DEFAULT_MIN_TEXT_CHARS, ge=0, le=100000),
    max_items: int = Query(default=500, ge=1, le=5000),
    write_reports: bool = Query(default=True),
) -> ZoteroAttachmentHealthResponse:
    """Return read-only Zotero attachment health diagnostics."""

    return build_zotero_attachment_health_response(
        zotero_data_dir=zotero_data_dir,
        allowed_root=allowed_root,
        min_text_chars=min_text_chars,
        max_items=max_items,
        write_reports=write_reports,
    )


__all__ = [
    "AttachmentHealthStatus",
    "ZOTERO_ATTACHMENT_HEALTH_SCHEMA_VERSION",
    "ZoteroAttachmentHealthResponse",
    "ZoteroAttachmentItem",
    "build_zotero_attachment_health_response",
    "router",
]
