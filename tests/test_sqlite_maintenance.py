# -*- coding: utf-8 -*-
"""Regression tests for the SQLite maintenance helpers and CLI."""

from __future__ import annotations

import json
from pathlib import Path

from db import (
    backup_sqlite_database,
    check_sqlite_integrity,
    checkpoint_sqlite_wal,
    collect_sqlite_health_report,
    get_sqlite_database_stats,
    open_sqlite_connection,
    restore_sqlite_database,
    vacuum_sqlite_database,
)
import sqlite_maintenance


def _seed_sqlite_db(db_path: Path, *, table_name: str, rows: list[tuple[str, str]]) -> None:
    with open_sqlite_connection(db_path) as conn:
        conn.execute(f"CREATE TABLE {table_name} (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.executemany(
            f"INSERT INTO {table_name} (id, value) VALUES (?, ?)",
            rows,
        )
        conn.commit()


def _fetch_single_value(db_path: Path, *, table_name: str, row_id: str) -> str:
    with open_sqlite_connection(db_path) as conn:
        row = conn.execute(
            f"SELECT value FROM {table_name} WHERE id = ?",
            (row_id,),
        ).fetchone()
    assert row is not None
    return str(row["value"])


def test_sqlite_helpers_round_trip_backup_restore(tmp_path: Path) -> None:
    source_db = tmp_path / "source.sqlite3"
    backup_db = tmp_path / "backup.sqlite3"
    restored_db = tmp_path / "restored.sqlite3"

    _seed_sqlite_db(source_db, table_name="records", rows=[("row-1", "alpha")])

    stats = get_sqlite_database_stats(source_db)
    assert stats["exists"] is True
    assert stats["size_bytes"] > 0

    health = collect_sqlite_health_report(source_db)
    assert health["ok"] is True
    assert health["integrity"]["ok"] is True

    checkpoint = checkpoint_sqlite_wal(source_db)
    assert checkpoint["ok"] is True

    vacuum = vacuum_sqlite_database(source_db)
    assert vacuum["ok"] is True
    assert vacuum["after"] is not None

    backup_sqlite_database(source_db, backup_db)
    restore_sqlite_database(backup_db, restored_db)

    assert check_sqlite_integrity(restored_db)["ok"] is True
    assert _fetch_single_value(restored_db, table_name="records", row_id="row-1") == "alpha"


def test_sqlite_maintenance_cli_backup_and_restore(tmp_path: Path, monkeypatch, capsys) -> None:
    runtime_db = tmp_path / "runtime.sqlite3"
    resource_db = tmp_path / "resources.sqlite3"
    backup_dir = tmp_path / "backup"

    _seed_sqlite_db(runtime_db, table_name="records", rows=[("runtime-1", "original-runtime")])
    _seed_sqlite_db(resource_db, table_name="records", rows=[("resource-1", "original-resource")])

    monkeypatch.setenv("WRITING_RUNTIME_DB_PATH", str(runtime_db))
    monkeypatch.setenv("WRITING_RESOURCE_DB_PATH", str(resource_db))

    health_exit = sqlite_maintenance.main(["health", "--target", "both"])
    health_output = json.loads(capsys.readouterr().out)
    assert health_exit == 0
    assert health_output["ok"] is True

    backup_exit = sqlite_maintenance.main(
        [
            "backup",
            "--destination",
            str(backup_dir),
            "--target",
            "both",
            "--snapshot-id",
            "pytest-snapshot",
        ]
    )
    backup_output = json.loads(capsys.readouterr().out)
    assert backup_exit == 0
    assert backup_output["ok"] is True
    assert (backup_dir / sqlite_maintenance.MANIFEST_FILENAME).exists()

    with open_sqlite_connection(runtime_db) as conn:
        conn.execute("UPDATE records SET value = ? WHERE id = ?", ("mutated-runtime", "runtime-1"))
        conn.commit()

    with open_sqlite_connection(resource_db) as conn:
        conn.execute("UPDATE records SET value = ? WHERE id = ?", ("mutated-resource", "resource-1"))
        conn.commit()

    restore_exit = sqlite_maintenance.main(["restore", "--source", str(backup_dir), "--target", "both"])
    restore_output = json.loads(capsys.readouterr().out)
    assert restore_exit == 0
    assert restore_output["ok"] is True

    assert _fetch_single_value(runtime_db, table_name="records", row_id="runtime-1") == "original-runtime"
    assert _fetch_single_value(resource_db, table_name="records", row_id="resource-1") == "original-resource"
