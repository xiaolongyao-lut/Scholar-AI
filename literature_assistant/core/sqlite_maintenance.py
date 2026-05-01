# -*- coding: utf-8 -*-
"""Command-line maintenance helpers for the writing SQLite databases."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from datetime_utils import utc_now_iso_z
from db import (
    backup_sqlite_database,
    checkpoint_sqlite_wal,
    check_sqlite_integrity,
    collect_sqlite_health_report,
    get_sqlite_database_stats,
    resolve_sqlite_path,
    restore_sqlite_database,
    vacuum_sqlite_database,
)

MANIFEST_FILENAME = "sqlite_maintenance_manifest.json"
MANAGED_TARGETS = ("runtime", "resources")


def get_managed_sqlite_targets() -> dict[str, Path]:
    """Return the managed SQLite databases used by the writing stack."""
    return {
        "runtime": resolve_sqlite_path("WRITING_RUNTIME_DB_PATH", "writing_runtime_state.sqlite3"),
        "resources": resolve_sqlite_path("WRITING_RESOURCE_DB_PATH", "writing_resources_state.sqlite3"),
    }


def _select_targets(target_scope: str) -> dict[str, Path]:
    targets = get_managed_sqlite_targets()
    scope = target_scope.strip().lower()
    if scope == "both":
        return targets
    if scope not in targets:
        raise ValueError(f"Unsupported target scope: {target_scope!r}")
    return {scope: targets[scope]}


def _sha256_file(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with file_path.open("rb") as handle:
        while chunk := handle.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def health_report(target_scope: str = "both") -> dict[str, Any]:
    """Collect health data for one or both managed databases."""
    reports: dict[str, Any] = {}
    for name, db_path in _select_targets(target_scope).items():
        reports[name] = collect_sqlite_health_report(db_path)
    return {
        "ok": all(report["ok"] for report in reports.values()),
        "created_at": utc_now_iso_z(),
        "targets": reports,
    }


def checkpoint_report(target_scope: str = "both", mode: str = "PASSIVE") -> dict[str, Any]:
    """Run a WAL checkpoint for one or both managed databases."""
    reports: dict[str, Any] = {}
    for name, db_path in _select_targets(target_scope).items():
        reports[name] = checkpoint_sqlite_wal(db_path, mode=mode)
    return {
        "ok": all(report["ok"] for report in reports.values()),
        "mode": mode.upper().strip(),
        "created_at": utc_now_iso_z(),
        "targets": reports,
    }


def vacuum_report(target_scope: str = "both", optimize: bool = True) -> dict[str, Any]:
    """Run VACUUM / optimize for one or both managed databases."""
    reports: dict[str, Any] = {}
    for name, db_path in _select_targets(target_scope).items():
        reports[name] = vacuum_sqlite_database(db_path, optimize=optimize)
    return {
        "ok": all(report["ok"] for report in reports.values()),
        "optimize": optimize,
        "created_at": utc_now_iso_z(),
        "targets": reports,
    }


def backup_report(destination_root: str | Path, target_scope: str = "both", snapshot_id: str | None = None) -> dict[str, Any]:
    """Back up one or both managed databases into a directory."""
    destination = Path(destination_root).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)

    databases: dict[str, Any] = {}
    for name, source_path in _select_targets(target_scope).items():
        backup_path = destination / source_path.name
        backup_sqlite_database(source_path, backup_path)
        databases[name] = {
            "source_path": str(source_path),
            "backup_path": str(backup_path),
            "sha256": _sha256_file(backup_path),
            "stats": get_sqlite_database_stats(backup_path),
            "integrity": check_sqlite_integrity(backup_path),
        }

    manifest = {
        "kind": "sqlite-maintenance-backup",
        "snapshot_id": snapshot_id or f"sqlite-backup-{utc_now_iso_z()}",
        "created_at": utc_now_iso_z(),
        "destination_root": str(destination),
        "targets": list(databases.keys()),
        "databases": databases,
        "ok": True,
    }
    manifest_path = destination / MANIFEST_FILENAME
    manifest_path.write_text(_dump_json(manifest), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def restore_report(source_root: str | Path, target_scope: str = "both") -> dict[str, Any]:
    """Restore one or both managed databases from a backup directory."""
    source = Path(source_root).expanduser().resolve()
    manifest_path = source / MANIFEST_FILENAME
    manifest: dict[str, Any] | None = None
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    restored: dict[str, Any] = {}
    targets = _select_targets(target_scope)
    for name, target_path in targets.items():
        if manifest and name in manifest.get("databases", {}):
            entry = manifest["databases"][name]
            backup_path = Path(entry["backup_path"])
            if not backup_path.is_absolute():
                backup_path = (source / backup_path).resolve()
            expected_checksum = entry.get("sha256")
        else:
            backup_path = source / target_path.name
            expected_checksum = None

        if not backup_path.exists():
            raise FileNotFoundError(f"Backup database not found: {backup_path}")

        if expected_checksum is not None:
            actual_checksum = _sha256_file(backup_path)
            if actual_checksum != expected_checksum:
                raise ValueError(
                    f"Checksum mismatch for {backup_path}: expected {expected_checksum}, got {actual_checksum}"
                )

        restore_sqlite_database(backup_path, target_path)
        restored[name] = {
            "backup_path": str(backup_path),
            "target_path": str(target_path),
            "integrity": check_sqlite_integrity(target_path),
        }

    return {
        "ok": all(entry["integrity"]["ok"] for entry in restored.values()),
        "created_at": utc_now_iso_z(),
        "source_root": str(source),
        "targets": restored,
        "manifest_path": str(manifest_path) if manifest_path.exists() else None,
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the maintenance CLI parser."""
    parser = argparse.ArgumentParser(description="Maintenance utilities for writing SQLite databases")
    subparsers = parser.add_subparsers(dest="command", required=True)

    health_parser = subparsers.add_parser("health", help="Inspect database health")
    health_parser.add_argument("--target", choices=("runtime", "resources", "both"), default="both")

    checkpoint_parser = subparsers.add_parser("checkpoint", help="Checkpoint the WAL")
    checkpoint_parser.add_argument("--target", choices=("runtime", "resources", "both"), default="both")
    checkpoint_parser.add_argument("--mode", choices=("PASSIVE", "FULL", "RESTART", "TRUNCATE"), default="PASSIVE")

    vacuum_parser = subparsers.add_parser("vacuum", help="Run VACUUM / optimize")
    vacuum_parser.add_argument("--target", choices=("runtime", "resources", "both"), default="both")
    vacuum_parser.add_argument("--no-optimize", action="store_true", help="Skip PRAGMA optimize after VACUUM")

    backup_parser = subparsers.add_parser("backup", help="Back up the managed databases")
    backup_parser.add_argument("--destination", required=True, help="Backup directory")
    backup_parser.add_argument("--target", choices=("runtime", "resources", "both"), default="both")
    backup_parser.add_argument("--snapshot-id", default=None, help="Optional manifest snapshot id")

    restore_parser = subparsers.add_parser("restore", help="Restore the managed databases from a backup directory")
    restore_parser.add_argument("--source", required=True, help="Backup directory")
    restore_parser.add_argument("--target", choices=("runtime", "resources", "both"), default="both")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for SQLite maintenance tasks."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "health":
            result = health_report(args.target)
        elif args.command == "checkpoint":
            result = checkpoint_report(args.target, mode=args.mode)
        elif args.command == "vacuum":
            result = vacuum_report(args.target, optimize=not args.no_optimize)
        elif args.command == "backup":
            result = backup_report(args.destination, args.target, snapshot_id=args.snapshot_id)
        elif args.command == "restore":
            result = restore_report(args.source, args.target)
        else:
            parser.error(f"Unsupported command: {args.command}")
            return 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(status=1, message=f"Error: {exc}\n")

    print(_dump_json(result))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
