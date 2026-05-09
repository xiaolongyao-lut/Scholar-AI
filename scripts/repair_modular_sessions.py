#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Idempotent repair/doctor script for modular sessions blob storage.

This script scans all sessions for blob orphans and zombie blobs, and can
repair them in a safe, idempotent manner.

Usage:
  python scripts/repair_modular_sessions.py --dry-run
  python scripts/repair_modular_sessions.py --apply --output repair_report.json
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def find_session_roots(workspace_root: Path | None = None) -> list[Path]:
    """Find all potential session database roots."""
    if workspace_root is None:
        workspace_root = Path.cwd()
    
    roots = []
    # Check .modular/sessions pattern (SQLite + transcripts/blobs dirs)
    modular_dir = workspace_root / ".modular" / "sessions"
    if modular_dir.exists():
        roots.append(modular_dir)
    
    # Also check in output/ for historical evaluation runs
    output_dir = workspace_root / "output"
    if output_dir.exists():
        for entry in output_dir.glob("**/writing_runtime_state.sqlite3"):
            roots.append(entry.parent)
    
    return roots


def scan_blob_orphans(session_root: Path) -> dict[str, Any]:
    """Scan for blob references that point to non-existent files."""
    orphans = []
    transcripts_dir = session_root / "transcripts"
    blobs_dir = session_root / "blobs"
    
    if not transcripts_dir.exists():
        return {"orphans": orphans, "missing_dirs": ["transcripts"]}
    
    missing_dirs = []
    if not blobs_dir.exists():
        missing_dirs.append("blobs")
    
    for transcript_file in transcripts_dir.glob("*.jsonl"):
        try:
            with transcript_file.open("r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                        payload = event.get("payload", {})
                        if isinstance(payload, dict) and payload.get("inlined") is False:
                            blob_ref = payload.get("blob_ref", {})
                            blob_path_str = blob_ref.get("blob_path")
                            if blob_path_str:
                                blob_path = Path(blob_path_str)
                                if not blob_path.exists():
                                    orphans.append({
                                        "transcript": transcript_file.name,
                                        "line": line_no,
                                        "event_id": event.get("event_id"),
                                        "blob_path": blob_path_str,
                                        "reason": "blob_file_not_found",
                                    })
                    except json.JSONDecodeError as e:
                        logger.warning("Malformed JSON in %s:%s: %s", transcript_file, line_no, e)
        except OSError as e:
            logger.warning("Cannot read transcript %s: %s", transcript_file, e)
    
    return {
        "orphans": orphans,
        "missing_dirs": missing_dirs,
    }


def scan_zombie_blobs(session_root: Path) -> dict[str, Any]:
    """Scan for blob files that are not referenced by any transcript."""
    zombies = []
    transcripts_dir = session_root / "transcripts"
    blobs_dir = session_root / "blobs"
    
    if not blobs_dir.exists():
        return {"zombies": zombies}
    
    # Collect all referenced blob paths
    referenced_blobs = set()
    if transcripts_dir.exists():
        for transcript_file in transcripts_dir.glob("*.jsonl"):
            try:
                with transcript_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line)
                            payload = event.get("payload", {})
                            if isinstance(payload, dict) and payload.get("inlined") is False:
                                blob_ref = payload.get("blob_ref", {})
                                blob_path_str = blob_ref.get("blob_path")
                                if blob_path_str:
                                    referenced_blobs.add(blob_path_str)
                        except json.JSONDecodeError:
                            pass
            except IOError:
                pass
    
    # Find unreferenced blobs
    for blob_file in blobs_dir.rglob("*.json"):
        blob_path_str = str(blob_file)
        if blob_path_str not in referenced_blobs:
            zombies.append({
                "blob_path": blob_path_str,
                "size_bytes": blob_file.stat().st_size,
                "reason": "no_transcript_reference",
            })
    
    return {"zombies": zombies}


def generate_repair_report(workspace_root: Path | None = None) -> dict[str, Any]:
    """Generate a comprehensive repair report."""
    roots = find_session_roots(workspace_root)
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "workspace_root": str(workspace_root or Path.cwd()),
        "session_roots_found": len(roots),
        "repairs": {
            "orphaned_blobs": {"count": 0, "details": []},
            "zombie_blobs": {"count": 0, "details": []},
            "missing_dirs": [],
        },
        "summary": {
            "total_orphans": 0,
            "total_zombies": 0,
            "is_clean": True,
        },
    }
    
    for root in roots:
        # Scan for orphans
        orphan_result = scan_blob_orphans(root)
        orphans = orphan_result.get("orphans", [])
        missing_dirs = orphan_result.get("missing_dirs", [])
        
        report["repairs"]["orphaned_blobs"]["details"].extend(orphans)
        report["repairs"]["orphaned_blobs"]["count"] += len(orphans)
        report["repairs"]["missing_dirs"].extend(missing_dirs)
        
        # Scan for zombies
        zombie_result = scan_zombie_blobs(root)
        zombies = zombie_result.get("zombies", [])
        report["repairs"]["zombie_blobs"]["details"].extend(zombies)
        report["repairs"]["zombie_blobs"]["count"] += len(zombies)
    
    report["summary"]["total_orphans"] = report["repairs"]["orphaned_blobs"]["count"]
    report["summary"]["total_zombies"] = report["repairs"]["zombie_blobs"]["count"]
    # Missing blobs/transcripts directories are informational in mixed roots
    # (e.g., historical output db snapshots) and should not mark the whole
    # workspace as unhealthy.
    report["summary"]["is_clean"] = (
        report["summary"]["total_orphans"] == 0 and
        report["summary"]["total_zombies"] == 0
    )
    
    return report


def apply_repairs(report: dict[str, Any], dry_run: bool = True) -> dict[str, Any]:
    """Apply repairs based on report. If dry_run=True, only simulate."""
    applied = {
        "dry_run": dry_run,
        "timestamp": datetime.now().isoformat(),
        "actions": [],
        "errors": [],
    }
    
    # Delete zombie blobs
    for zombie in report["repairs"]["zombie_blobs"]["details"]:
        blob_path_str = zombie.get("blob_path")
        if blob_path_str:
            blob_path = Path(blob_path_str)
            if dry_run:
                applied["actions"].append({
                    "action": "would_delete_zombie_blob",
                    "path": blob_path_str,
                    "size_bytes": zombie.get("size_bytes"),
                })
            else:
                try:
                    blob_path.unlink()
                    applied["actions"].append({
                        "action": "deleted_zombie_blob",
                        "path": blob_path_str,
                    })
                except OSError as e:
                    applied["errors"].append({
                        "action": "delete_zombie_blob_failed",
                        "path": blob_path_str,
                        "error": str(e),
                    })
    
    # Create missing directories
    for root_str in [report.get("workspace_root")]:
        if root_str and "blobs" in report["repairs"]["missing_dirs"]:
            blobs_dir = Path(root_str) / ".modular" / "sessions" / "blobs"
            if dry_run:
                applied["actions"].append({
                    "action": "would_create_dir",
                    "path": str(blobs_dir),
                })
            else:
                try:
                    blobs_dir.mkdir(parents=True, exist_ok=True)
                    applied["actions"].append({
                        "action": "created_dir",
                        "path": str(blobs_dir),
                    })
                except OSError as e:
                    applied["errors"].append({
                        "action": "create_dir_failed",
                        "path": str(blobs_dir),
                        "error": str(e),
                    })
    
    applied["is_clean"] = (
        report["summary"]["is_clean"] or
        (len(applied["errors"]) == 0 and len(report["repairs"]["zombie_blobs"]["details"]) > 0)
    )
    
    return applied


def main():
    parser = argparse.ArgumentParser(
        description="Repair modular sessions blob storage (S-1 Path D doctor script)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report issues without making changes",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply repairs (requires --dry-run to be verified first)",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Write repair report to JSON file",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        help="Workspace root (default: current directory)",
    )
    
    args = parser.parse_args()
    
    workspace_root = Path(args.workspace) if args.workspace else Path.cwd()
    
    logger.info("Scanning sessions in %s", workspace_root)
    report = generate_repair_report(workspace_root)
    
    logger.info("Found %s orphaned blobs", report["summary"]["total_orphans"])
    logger.info("Found %s zombie blobs", report["summary"]["total_zombies"])
    
    if args.apply:
        applied = apply_repairs(report, dry_run=False)
        logger.info("Applied %s repairs", len(applied["actions"]))
        if applied["errors"]:
            logger.warning("Encountered %s errors", len(applied["errors"]))
        
        if args.output:
            output_path = Path(args.output)
            output_path.write_text(json.dumps(applied, indent=2), encoding="utf-8")
            logger.info("Repair report written to %s", output_path)
    else:
        # Dry run (default)
        applied = apply_repairs(report, dry_run=True)
        logger.info("Would apply %s repairs", len(applied["actions"]))
        
        if args.output:
            output_path = Path(args.output)
            output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            logger.info("Scan report written to %s", output_path)
    
    if report["summary"]["is_clean"]:
        logger.info("✅ All sessions are clean - no repairs needed")
        return 0
    else:
        logger.warning("⚠️  %s issues found", report["summary"]["total_orphans"] + report["summary"]["total_zombies"])
        return 1


if __name__ == "__main__":
    exit(main())
