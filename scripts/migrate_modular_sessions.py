"""Idempotent health-check / migration for .modular/sessions/ persistence.

Plan: docs/superpowers/plans/2026-04-20-conversation-persistence-mvp.md §10 (D-5)

Scope is intentionally narrow per the D-plan:
  - Verify the SQLite file opens and its schema version is current.
  - Ensure transcripts/ and blobs/ directories exist (mkdir -p, atomic).
  - Report counts (sessions / transcript files / blob files).
  - `--dry-run` prints the plan without touching disk.

This script does NOT:
  - Rename tables (jobs/events/artifacts -> turns/tool_calls/branches) — out of scope.
  - Move blobs to per-session subdirectories — out of scope.
  - Delete or rewrite data.
  If those become necessary, re-open the D-plan §10.4 "trigger conditions".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from repositories.writing_runtime_repository import WritingRuntimeRepository  # noqa: E402


def _default_db_path() -> Path:
    return Path.cwd() / ".modular" / "sessions" / "index.sqlite3"


def inspect(db_path: Path, *, dry_run: bool) -> dict[str, object]:
    """Ensure storage layout exists and return a small health summary."""
    db_path = db_path.expanduser().resolve()
    storage_root = db_path.parent
    transcripts_dir = storage_root / "transcripts"
    blobs_dir = storage_root / "blobs"

    actions: list[str] = []
    if not storage_root.exists():
        actions.append(f"mkdir -p {storage_root}")
    if not transcripts_dir.exists():
        actions.append(f"mkdir -p {transcripts_dir}")
    if not blobs_dir.exists():
        actions.append(f"mkdir -p {blobs_dir}")

    if dry_run:
        return {
            "dry_run": True,
            "db_path": str(db_path),
            "planned_actions": actions,
            "db_exists": db_path.exists(),
        }

    # Instantiating the repository creates directories + ensures schema. This
    # is the idempotent contract we rely on for migration/health: re-running
    # must not corrupt anything.
    repo = WritingRuntimeRepository(db_path)

    transcript_files = sorted(repo.transcripts_dir.glob("*.jsonl"))
    blob_files = sorted(repo.blobs_dir.glob("*.json"))

    try:
        snapshot = repo.load_state()
        session_count = len(snapshot.get("sessions") or {})
    except Exception as exc:  # noqa: BLE001 — health report, do not raise
        return {
            "dry_run": False,
            "db_path": str(db_path),
            "status": "error",
            "error": repr(exc),
            "applied_actions": actions,
        }

    return {
        "dry_run": False,
        "db_path": str(db_path),
        "status": "ok",
        "applied_actions": actions,
        "counts": {
            "sessions": session_count,
            "transcript_files": len(transcript_files),
            "blob_files": len(blob_files),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        type=Path,
        default=_default_db_path(),
        help="Path to the writing-runtime SQLite file (default: ./.modular/sessions/index.sqlite3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without touching disk.",
    )
    args = parser.parse_args(argv)

    report = inspect(args.db_path, dry_run=args.dry_run)
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if report.get("status") != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
