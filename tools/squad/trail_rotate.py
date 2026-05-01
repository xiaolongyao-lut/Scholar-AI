#!/usr/bin/env python3
"""Rotate .squad/memory/DECISION_TRAIL.md when it grows past a soft cap.

Sibling of tools/squad/pool_rotate.py. Discharges the implementation-side
followup for .squad/specs/trail-archival.md (round-13 trail line 124818
followup #1, "tools/squad/trail_rotate.py implementation"). Lockfile and
acquire/release helpers come from .squad/tools/trail_append.py verbatim,
mirroring pool_rotate.py's relationship with pool_append.py.

Why this exists
---------------
trail_append.py grows DECISION_TRAIL.md without bound. By round-18
(2026-04-25 12:58) the trail was 1,940,431 bytes / ~485K tokens — well
past the 300_000-token "archival authorised" threshold defined by
trail-archival.md §1. check-trail-size.ps1 / check_trail_size.py emit
exit code 2 on this state, but until this script lands there is no
operational primitive that performs the rotation.

What this does
--------------
1. Reads DECISION_TRAIL.md under the SAME lockfile trail_append.py uses,
   so concurrent appenders from parallel-Morpheus instances block.
2. Splits the file into:
   - header (everything before the first '^### \\[' anchor),
   - entries (each block from a '^### \\[' anchor up to the next anchor).
3. Per trail-archival.md §2, archives the OLDEST 40% of entries by file
   position (top-of-file = oldest, append-only invariant). The boundary
   is rounded forward to the next '^### \\[' anchor so entries are moved
   whole — never mid-entry.
4. Writes both files atomically (.tmp + os.replace) inside the same
   single critical section. Reader after lock release sees either both
   old or both new; never half-rotated.
5. Prints a one-line SUMMARY for the operator audit log.

Threshold note
--------------
This script does NOT enforce the 300K-token threshold. Per
trail-archival.md §3 ("Trigger: archival is never automatic"), threshold
detection is the job of check-trail-size.ps1; the actual archival pass
is a deliberate, attributable act invoked by an operator (or a future
trigger-policy script that records the in-trail authorisation line per
§3 first). This script just performs the rotation when invoked.

Usage
-----
    py -3 tools/squad/trail_rotate.py [--cut-fraction 0.40] [--dry-run]
                                       [--timeout 30]

The default --cut-fraction 0.40 matches trail-archival.md §2's mechanical
40%-oldest selection. Operators MAY override for a smaller pass, but the
spec's anti-cherry-pick clause means the slice is always file-position
oldest-first — there is no flag to select by score, status, or agent.

Exit codes
----------
0 success (or no-op if no archivable entries)
1 lock acquisition failed
2 unrecoverable (header parse failure, no '### [' anchors)
"""
from __future__ import annotations
import argparse
import datetime as _dt
import os
import re
import sys
from pathlib import Path

# Reuse the lock primitive verbatim from trail_append.py — same rationale as
# pool_rotate.py importing pool_append: any future hardening of acquire()/
# release() lands in both tools simultaneously.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".squad" / "tools"))
import trail_append  # type: ignore[import-not-found]

TRAIL = ROOT / ".squad" / "memory" / "DECISION_TRAIL.md"
LOCK = TRAIL.parent / ".DECISION_TRAIL.md.lock"  # MATCHES trail_append.py

# H3 anchor pattern. Trail entries start with "### [" followed by a
# timestamp — the canonical header pattern named in trail-archival.md §2.
H3_RE = re.compile(rb"(?m)^### \[")


def split_trail(buf: bytes) -> tuple[bytes, list[bytes]]:
    """Return (header_bytes, [entry_bytes, ...]).

    Header = everything before the first '^### \\[' anchor. Each entry
    begins at an anchor line and runs up to (but not including) the next
    anchor. Trailing newlines are preserved on each entry so concatenating
    kept-entries reproduces original byte-content verbatim.
    """
    matches = list(H3_RE.finditer(buf))
    if not matches:
        return buf, []
    header = buf[: matches[0].start()]
    entries: list[bytes] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(buf)
        entries.append(buf[m.start() : end])
    return header, entries


def select_oldest_slice(entries: list[bytes], cut_fraction: float) -> tuple[list[bytes], list[bytes]]:
    """Return (archived_entries, kept_entries) per trail-archival.md §2.

    Mechanical oldest-by-file-position cut: walks entries from the head
    accumulating bytes until cumulative >= cut_fraction * total_bytes,
    then rounds forward to that entry's end (entries are moved whole —
    boundary discipline per §2). The cut is never mid-entry.

    Anti-cherry-pick: no parameter selects by score/status/agent. The
    fraction is the only knob; default 0.40 per spec.
    """
    if not entries:
        return [], []
    total = sum(len(e) for e in entries)
    target = total * cut_fraction
    cum = 0
    cut_idx = 0  # number of entries archived (head-side)
    for i, e in enumerate(entries):
        cum += len(e)
        if cum >= target:
            cut_idx = i + 1  # include this entry (round forward to its end)
            break
    # Edge: cut_fraction so small no entry crosses target — archive the head
    # entry only (still oldest-by-position; preserves "always make progress").
    if cut_idx == 0 and cut_fraction > 0.0:
        cut_idx = 1
    archived = entries[:cut_idx]
    kept = entries[cut_idx:]
    return archived, kept


def archive_path() -> Path:
    today = _dt.datetime.now().strftime("%Y%m%d")
    return TRAIL.parent / f"DECISION_TRAIL-archive-{today}.md"


def atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def atomic_append_with_separator(path: Path, data: bytes, ts: str) -> None:
    """Append-or-create with atomic semantics + per-pass separator.

    trail-archival.md §4: 'Same-day re-pass appends after \\n---\\n## Archival
    pass <timestamp>\\n\\n'. The separator is omitted for the FIRST write of
    a fresh archive file (no prior content to delimit from).
    """
    cur = path.read_bytes() if path.exists() else b""
    sep = b""
    if cur:
        sep = f"\n---\n## Archival pass {ts}\n\n".encode("utf-8")
    atomic_write(path, cur + sep + data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cut-fraction", type=float, default=0.40,
                    help="fraction of oldest entries to archive (default 0.40 per "
                         "trail-archival.md §2)")
    ap.add_argument("--timeout", type=float, default=30.0,
                    help="lock acquisition timeout in seconds (default 30)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would happen, do not write")
    args = ap.parse_args()

    if not (0.0 < args.cut_fraction < 1.0):
        sys.stderr.write(
            f"[trail-rotate] --cut-fraction must be in (0, 1); got {args.cut_fraction}\n"
        )
        return 2

    if not TRAIL.exists():
        print(f"[trail-rotate] no trail at {TRAIL}; nothing to do")
        return 0

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if not LOCK.exists() or LOCK.stat().st_size == 0:
        LOCK.write_bytes(b"\0")

    bytes_before = TRAIL.stat().st_size

    with LOCK.open("r+b") as lockfh:
        if not trail_append.acquire(lockfh, args.timeout):
            sys.stderr.write(
                f"[trail-rotate] could not acquire lock within {args.timeout}s\n"
            )
            return 1
        try:
            buf = TRAIL.read_bytes()
            header, entries = split_trail(buf)
            if not entries:
                print("[trail-rotate] no '### [' anchors found; abort to avoid "
                      "corrupting non-conforming trail")
                return 2
            archived, kept = select_oldest_slice(entries, args.cut_fraction)
            if not archived:
                print(f"[trail-rotate] cut_fraction {args.cut_fraction} produced "
                      f"empty slice across {len(entries)} entries; no-op")
                return 0

            new_trail = header + b"".join(kept)
            archive_blob = b"".join(archived)
            arch = archive_path()
            ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            summary = (
                f"[trail-rotate] entries_before={len(entries)} "
                f"entries_archived={len(archived)} entries_kept={len(kept)} "
                f"bytes_before={bytes_before} bytes_after={len(new_trail)} "
                f"archive={arch.name} archive_bytes_appended={len(archive_blob)} "
                f"cut_fraction={args.cut_fraction}"
            )

            if args.dry_run:
                print(f"[trail-rotate] DRY-RUN {summary}")
                return 0

            # Single critical section: archive append + trail rewrite both
            # land before lock release. Reader after release sees either
            # both old or both new — never half-rotated.
            atomic_append_with_separator(arch, archive_blob, ts)
            atomic_write(TRAIL, new_trail)
            print(summary)
            return 0
        finally:
            trail_append.release(lockfh)


if __name__ == "__main__":
    sys.exit(main())
