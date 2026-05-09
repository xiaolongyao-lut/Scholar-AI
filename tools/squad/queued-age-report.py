#!/usr/bin/env python3
"""queued-age-report — per-task age histogram for unleased queued tasks.

Read-only diagnostic. Triage data for the 50/50 worker-lease blackout: which
specific tasks are oldest, on which agent, in which age bucket.

Spec anchor: requirement-pool 39/50 SELF-APPLIED-NEXT-ROUND entry, round 074818.

Pure stdlib (subprocess/sqlite3/json/pathlib/datetime/re/os). No deps. No mutation.
Output: .squad/diagnostics/queued-age-<UTC>.json (atomic .tmp + os.replace).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DIAG_DIR = REPO_ROOT / ".squad" / "diagnostics"
DB_PATH = REPO_ROOT / ".squad" / "messages.db"

BUCKETS = [
    ("<30m", 0, 30),
    ("30-120m", 30, 120),
    ("2-12h", 120, 12 * 60),
    (">12h", 12 * 60, None),
]


def bucket_for(age_minutes):
    if age_minutes is None:
        return "?"
    for name, lo, hi in BUCKETS:
        if hi is None and age_minutes >= lo:
            return name
        if lo <= age_minutes < hi:
            return name
    return "?"


def list_queued_ids():
    """Scrape `squad task list --status queued` for task ids (CLI is the truth)."""
    try:
        out = subprocess.run(
            ["squad", "task", "list", "--status", "queued"],
            capture_output=True, timeout=30, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return None, f"squad CLI failure: {exc!r}"
    if out.returncode != 0:
        return None, f"squad exited {out.returncode}: {out.stderr[:200]!r}"
    text = out.stdout.decode("utf-8", errors="replace")
    return re.findall(r"\[task ([0-9a-f-]{36})\] queued", text), None


def enrich_from_db(ids):
    """READ-ONLY sqlite lookup for created_at + lease_owner. Returns list of dicts."""
    if not DB_PATH.exists() or not ids:
        return []
    rows = []
    # sqlite3 read-only via URI mode=ro
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        cur = con.cursor()
        placeholders = ",".join("?" * len(ids))
        cur.execute(
            f"SELECT id, title, assigned_to, lease_owner, created_at "
            f"FROM tasks WHERE id IN ({placeholders})",
            ids,
        )
        rows = cur.fetchall()
    finally:
        con.close()
    return rows


def main():
    now_epoch = int(time.time())
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    ids, err = list_queued_ids()
    if ids is None:
        print(f"queued-age-report: ERROR {err}", file=sys.stderr)
        return 1

    rows = enrich_from_db(ids)

    enriched = []
    by_assigned = {}
    by_bucket = {name: 0 for name, _, _ in BUCKETS}
    by_bucket["?"] = 0
    unleased_count = 0

    for tid, title, assigned, lease_owner, created in rows:
        age_min = None
        if isinstance(created, int):
            age_min = max(0, (now_epoch - created) // 60)
        b = bucket_for(age_min)
        by_bucket[b] = by_bucket.get(b, 0) + 1
        by_assigned[assigned or "?"] = by_assigned.get(assigned or "?", 0) + 1
        if (lease_owner or "unleased") == "unleased":
            unleased_count += 1
        enriched.append({
            "id": tid,
            "title": (title or "")[:120],
            "assigned_to": assigned,
            "lease_owner": lease_owner or "unleased",
            "age_minutes": age_min,
            "age_bucket": b,
        })

    enriched.sort(key=lambda r: -(r["age_minutes"] or -1))
    oldest_n = enriched[:10]

    payload = {
        "schema_version": "v0",
        "run_id": f"queued-age-{now_iso.replace(':', '').replace('-', '')}",
        "captured_at": now_iso,
        "total_queued": len(ids),
        "total_enriched": len(rows),
        "unleased_count": unleased_count,
        "by_assigned": by_assigned,
        "by_bucket": by_bucket,
        "oldest_n": oldest_n,
        "notes": (
            "READ-ONLY diagnostic. CLI scrape + sqlite ro=true. No task mutation. "
            "If total_enriched < total_queued, some ids were not in messages.db "
            "(stale CLI cache or cross-db drift)."
        ),
    }

    DIAG_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"queued-age-{now_iso.replace(':', '').replace('-', '')}.json"
    out_path = DIAG_DIR / fname
    tmp_path = out_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, out_path)

    oldest = oldest_n[0] if oldest_n else None
    if oldest:
        print(
            f"queued-age-report: total={len(ids)}, oldest={oldest['id'][:8]} "
            f"({oldest['age_minutes']}m) on {oldest['assigned_to']}, wrote={out_path}"
        )
    else:
        print(f"queued-age-report: total={len(ids)}, no rows, wrote={out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
