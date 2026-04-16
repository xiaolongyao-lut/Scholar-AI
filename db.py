# -*- coding: utf-8 -*-
"""Shared SQLite helpers for durable writing stores."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


def resolve_sqlite_path(env_var: str, default_filename: str, base_dir: Path | None = None) -> Path:
    """Resolve a SQLite database path from environment or a stable repo-local default."""
    configured_path = os.environ.get(env_var, "").strip()
    if configured_path:
        return Path(configured_path).expanduser().resolve()

    root_dir = base_dir or Path(__file__).resolve().parent
    return (root_dir / "output" / default_filename).resolve()


def open_sqlite_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with durability-friendly defaults."""
    path = Path(db_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def json_dumps(value: Any) -> str:
    """Serialize a JSON-safe value using stable UTF-8 encoding."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads(value: Any, default: Any = None) -> Any:
    """Deserialize a JSON column, falling back to a default when empty."""
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    return json.loads(value)


def closing_sqlite(db_path: str | Path):
    """Open a SQLite connection inside a closing() wrapper."""
    return closing(open_sqlite_connection(db_path))


def _normalize_sqlite_path(db_path: str | Path) -> Path:
    """Normalize a SQLite path to an absolute filesystem location."""
    return Path(db_path).expanduser().resolve()


def _sqlite_sidecar_path(db_path: Path, suffix: str) -> Path:
    """Return the WAL or SHM sidecar path for a database file."""
    return db_path.with_name(f"{db_path.name}{suffix}")


def _sqlite_file_size(db_path: Path) -> int:
    """Return the size of a SQLite-related file when it exists."""
    try:
        return db_path.stat().st_size
    except OSError:
        return 0


def _connect_existing_sqlite(db_path: Path) -> sqlite3.Connection:
    """Open an inspection connection to an existing SQLite file."""
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def get_sqlite_database_stats(db_path: str | Path) -> dict[str, Any]:
    """Collect file and pragma-based size statistics for a SQLite database."""
    path = _normalize_sqlite_path(db_path)
    stats: dict[str, Any] = {
        "db_path": str(path),
        "exists": path.exists(),
        "size_bytes": _sqlite_file_size(path),
        "wal_size_bytes": _sqlite_file_size(_sqlite_sidecar_path(path, "-wal")),
        "shm_size_bytes": _sqlite_file_size(_sqlite_sidecar_path(path, "-shm")),
        "page_count": 0,
        "page_size": 0,
        "freelist_count": 0,
        "journal_mode": None,
        "error": None,
    }

    if not stats["exists"]:
        return stats

    try:
        with _connect_existing_sqlite(path) as conn:
            row = conn.execute("PRAGMA page_count").fetchone()
            if row is not None and row[0] is not None:
                stats["page_count"] = int(row[0])

            row = conn.execute("PRAGMA page_size").fetchone()
            if row is not None and row[0] is not None:
                stats["page_size"] = int(row[0])

            row = conn.execute("PRAGMA freelist_count").fetchone()
            if row is not None and row[0] is not None:
                stats["freelist_count"] = int(row[0])

            row = conn.execute("PRAGMA journal_mode").fetchone()
            if row is not None and row[0] is not None:
                stats["journal_mode"] = str(row[0])
    except sqlite3.Error as exc:
        stats["error"] = str(exc)

    return stats


def check_sqlite_integrity(db_path: str | Path) -> dict[str, Any]:
    """Run SQLite integrity and foreign-key checks against a database file."""
    path = _normalize_sqlite_path(db_path)
    report: dict[str, Any] = {
        "db_path": str(path),
        "exists": path.exists(),
        "check": "integrity_check",
        "ok": False,
        "result": [],
        "foreign_key_violations": [],
        "issues": [],
        "error": None,
    }

    if not report["exists"]:
        report["issues"] = ["database file does not exist"]
        return report

    try:
        with _connect_existing_sqlite(path) as conn:
            result = [str(row[0]) for row in conn.execute("PRAGMA integrity_check")]
            fk_violations = [
                {
                    "table": str(row[0]),
                    "rowid": None if row[1] is None else int(row[1]),
                    "parent": None if row[2] is None else str(row[2]),
                    "fkid": None if row[3] is None else int(row[3]),
                }
                for row in conn.execute("PRAGMA foreign_key_check")
            ]
    except sqlite3.Error as exc:
        report["error"] = str(exc)
        report["issues"] = [str(exc)]
        return report

    report["result"] = result
    report["foreign_key_violations"] = fk_violations
    issues = [entry for entry in result if entry != "ok"]
    issues.extend(
        (
            "foreign key violation: "
            f"table={violation['table']} rowid={violation['rowid']} parent={violation['parent']} fkid={violation['fkid']}"
        )
        for violation in fk_violations
    )
    report["issues"] = issues
    report["ok"] = result == ["ok"] and not fk_violations
    return report


def collect_sqlite_health_report(db_path: str | Path) -> dict[str, Any]:
    """Collect a combined health report for a SQLite database file."""
    stats = get_sqlite_database_stats(db_path)
    integrity = check_sqlite_integrity(db_path)
    return {
        "db_path": stats["db_path"],
        "exists": bool(stats["exists"]),
        "ok": bool(stats["exists"] and stats["error"] is None and integrity["ok"]),
        "stats": stats,
        "integrity": integrity,
    }


def checkpoint_sqlite_wal(db_path: str | Path, mode: str = "PASSIVE") -> dict[str, Any]:
    """Run a WAL checkpoint against a SQLite database."""
    path = _normalize_sqlite_path(db_path)
    checkpoint_mode = mode.upper().strip()
    allowed_modes = {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}
    if checkpoint_mode not in allowed_modes:
        raise ValueError(f"Unsupported WAL checkpoint mode: {mode!r}")

    report: dict[str, Any] = {
        "db_path": str(path),
        "exists": path.exists(),
        "mode": checkpoint_mode,
        "ok": False,
        "busy": None,
        "log_frames": None,
        "checkpointed_frames": None,
        "error": None,
    }

    if not report["exists"]:
        report["error"] = "database file does not exist"
        return report

    try:
        with _connect_existing_sqlite(path) as conn:
            row = conn.execute(f"PRAGMA wal_checkpoint({checkpoint_mode})").fetchone()
    except sqlite3.Error as exc:
        report["error"] = str(exc)
        return report

    if row is not None:
        report["busy"] = int(row[0]) if row[0] is not None else None
        report["log_frames"] = int(row[1]) if row[1] is not None else None
        report["checkpointed_frames"] = int(row[2]) if row[2] is not None else None
    report["ok"] = True
    return report


def vacuum_sqlite_database(db_path: str | Path, optimize: bool = True) -> dict[str, Any]:
    """Run VACUUM and optionally PRAGMA optimize against a SQLite database."""
    path = _normalize_sqlite_path(db_path)
    report: dict[str, Any] = {
        "db_path": str(path),
        "exists": path.exists(),
        "ok": False,
        "before": get_sqlite_database_stats(path),
        "after": None,
        "optimize": optimize,
        "error": None,
    }

    if not report["exists"]:
        report["error"] = "database file does not exist"
        return report

    try:
        with _connect_existing_sqlite(path) as conn:
            conn.isolation_level = None
            conn.execute("VACUUM")
            if optimize:
                conn.execute("PRAGMA optimize")
    except sqlite3.Error as exc:
        report["error"] = str(exc)
        report["after"] = get_sqlite_database_stats(path)
        return report

    report["after"] = get_sqlite_database_stats(path)
    report["ok"] = True
    return report


def _copy_sqlite_database(source_path: str | Path, target_path: str | Path) -> Path:
    """Copy one SQLite database file into another location using SQLite backup."""
    source = _normalize_sqlite_path(source_path)
    target = _normalize_sqlite_path(target_path)

    if source == target:
        raise ValueError("source and target paths must be different")
    if not source.exists():
        raise FileNotFoundError(f"SQLite database does not exist: {source}")

    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(source), timeout=10.0) as source_conn:
        with sqlite3.connect(str(target), timeout=10.0) as target_conn:
            source_conn.backup(target_conn)
    return target


def backup_sqlite_database(source_path: str | Path, backup_path: str | Path) -> Path:
    """Create a SQLite backup copy of a database file."""
    return _copy_sqlite_database(source_path, backup_path)


def restore_sqlite_database(backup_path: str | Path, target_path: str | Path) -> Path:
    """Restore a SQLite database file from a backup copy."""
    return _copy_sqlite_database(backup_path, target_path)
