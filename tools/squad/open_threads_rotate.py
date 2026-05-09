#!/usr/bin/env python3
"""Rotate .squad/memory/OPEN_THREADS.md per .squad/specs/open-threads-archival.md.

Third executor in the squad-memory rotation toolchain (siblings: pool_rotate.py,
trail_rotate.py). Discharges the named-but-unwritten executor implied by
.squad/specs/open-threads-archival.md (the spec defines policy; this is the
operational glue).

Why this exists
---------------
OPEN_THREADS.md is preventively governed by open-threads-archival.md (currently
~21,812 bytes, well under the 50K-token threshold). With pool and trail
rotation toolchains both shipped, leaving OPEN_THREADS without an executor
creates an asymmetry: monitor exists (.squad/tools/check-open-threads-size.ps1
landed earlier), spec exists (open-threads-archival.md), executor virgin.
This file closes that gap before the threshold is crossed, per the spec's
"PREVENTIVE — written ahead of need to avoid panicked-design-under-pressure"
authoring intent.

What this does (per open-threads-archival.md §2)
-----------------------------------------------
1. Reads OPEN_THREADS.md under a sibling lockfile so concurrent edits block.
2. Splits the file into:
   - prefix (lines before '^## Closed' header — includes '## Active' section
     and any pre-Active prelude),
   - closed_header ('## Closed' line + any blank line after),
   - closed_entries (each '- [...] ...' block in the Closed section, including
     all indented continuation lines until the next '- [' or end-of-file).
3. Archives the OLDEST 50% of closed_entries by file position, EXCEPT entries
   closed within the last 7 days (recency exemption per §2). Recency is
   detected by the '✅ closed YYYY-MM-DD' or 'CLOSED YYYY-MM-DD' marker in
   the entry's first line; entries without a parseable date are treated as
   non-recent (eligible).
4. Writes both files atomically (.tmp + os.replace) inside the same single
   critical section. Reader after release sees either both old or both new —
   never half-rotated.
5. Each archived entry leaves a single-line stub at its original position
   per §5 stub preservation: '- [<thread-name>] ✅ ARCHIVED YYYYMMDD →
   .squad/memory/OPEN_THREADS-archive-YYYYMMDD.md'.

Lock primitive
--------------
Imports acquire/release from .squad/tools/trail_append.py. Same OS primitive
(msvcrt on Windows, fcntl on POSIX) but DIFFERENT lockfile path
(.squad/memory/.OPEN_THREADS.md.lock) so the two locks don't cross-block.

Usage
-----
    py -3 tools/squad/open_threads_rotate.py [--cut-fraction 0.50]
                                             [--exempt-days 7] [--dry-run]
                                             [--timeout 30]

Defaults match open-threads-archival.md §2: cut_fraction=0.50, exempt_days=7.

Exit codes
----------
0 success (or no-op if no archivable entries after exemption)
1 lock acquisition failed
2 unrecoverable (no '## Closed' header found, etc.)
"""
from __future__ import annotations
import argparse
import datetime as _dt
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".squad" / "tools"))
import trail_append  # type: ignore[import-not-found]  # reuse acquire/release primitive

THREADS = ROOT / ".squad" / "memory" / "OPEN_THREADS.md"
LOCK = THREADS.parent / ".OPEN_THREADS.md.lock"  # SIBLING — does not collide with trail lock

# Section header for the Closed block. Spec §2 explicitly requires this exact
# header — it is the boundary marker; never moved by archival.
CLOSED_HEADER_RE = re.compile(rb"(?m)^## Closed\s*$")

# Entry start: '- [<name>]' at column 0 inside the Closed section.
ENTRY_START_RE = re.compile(rb"(?m)^- \[")

# Recency markers for §2 exemption. Examples seen in OPEN_THREADS.md:
#   "- [team-memory-adoption] ✅ closed 2026-04-20"
#   "- [intelligent-chat-hard-stop] ✅ CLOSED 2026-04-20 → ..."
#   "- [rag-eval-daemon-stale] ✅ AUTO-CLOSE APPLIED 2026-04-25 10:54 ..."
DATE_IN_FIRST_LINE_RE = re.compile(rb"\b(\d{4}-\d{2}-\d{2})\b")


def split_threads(buf: bytes) -> tuple[bytes, bytes, list[bytes]]:
    """Return (prefix, closed_header, closed_entries).

    prefix = everything before the '## Closed' header line (inclusive of '## Active'
             section and its entries; those are NEVER archived per §2).
    closed_header = the '## Closed\\n' line plus an optional blank line after.
    closed_entries = each entry block from '- [' anchor to (but not including)
                     the next '- [' anchor or end-of-file. Entries preserve
                     trailing newlines for byte-faithful reassembly.
    """
    m = CLOSED_HEADER_RE.search(buf)
    if not m:
        return buf, b"", []
    # closed_header ends at first newline after the match; consume one optional
    # blank line so entries reassemble cleanly with their leading newline.
    hdr_end = buf.find(b"\n", m.end())
    if hdr_end == -1:
        hdr_end = len(buf)
    else:
        hdr_end += 1  # include the newline
    # Optional second newline (blank line after '## Closed').
    if hdr_end < len(buf) and buf[hdr_end : hdr_end + 1] == b"\n":
        hdr_end += 1
    prefix = buf[: m.start()]
    closed_header = buf[m.start() : hdr_end]
    closed_body = buf[hdr_end:]
    # Split closed_body on entry-start anchors.
    starts = [match.start() for match in ENTRY_START_RE.finditer(closed_body)]
    if not starts:
        return prefix, closed_header, []
    # Anything before the first '- [' in closed_body (e.g. blank line) is
    # appended back onto closed_header so reassembly is verbatim.
    if starts[0] > 0:
        closed_header = closed_header + closed_body[: starts[0]]
    entries: list[bytes] = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(closed_body)
        entries.append(closed_body[s:e])
    return prefix, closed_header, entries


def entry_is_recent(entry: bytes, today: _dt.date, exempt_days: int) -> bool:
    """Per §2 exemption: True if entry was closed within last `exempt_days`.

    Searches first line for any YYYY-MM-DD; takes the latest such date.
    Entries without a parseable date are treated as NON-RECENT (eligible for
    archival) — the spec says "entries without a parseable date are treated
    as non-recent" via implication.
    """
    first_line = entry.split(b"\n", 1)[0]
    matches = DATE_IN_FIRST_LINE_RE.findall(first_line)
    if not matches:
        return False
    try:
        dates = [
            _dt.date(int(m[:4]), int(m[5:7]), int(m[8:10]))
            for m in (s.decode("ascii") for s in matches)
        ]
    except (ValueError, UnicodeDecodeError):
        return False
    latest = max(dates)
    return (today - latest).days < exempt_days


def entry_thread_name(entry: bytes) -> str:
    """Extract '<thread-name>' from leading '- [<thread-name>]'."""
    m = re.match(rb"- \[([^\]]+)\]", entry)
    if not m:
        return "unknown"
    return m.group(1).decode("utf-8", errors="replace")


def select_oldest_eligible(
    entries: list[bytes], cut_fraction: float, exempt_days: int, today: _dt.date
) -> tuple[list[bytes], list[bytes], list[bytes]]:
    """Per §2: oldest cut_fraction by file position, except entries within
    exempt_days of today.

    Returns (archived, kept_recent, kept_remainder) where:
      archived       = entries selected for archival (oldest, non-recent)
      kept_recent    = entries that fell in the slice but are exempt (recency)
      kept_remainder = entries past the cut point (newest, kept regardless)

    The reassembly order is: kept_recent (in original positions) +
    kept_remainder (in original positions) — preserving file-position order.
    """
    if not entries:
        return [], [], []
    cut_idx = int(len(entries) * cut_fraction)
    # Round forward at least 1 entry if cut_fraction > 0 and entries exist.
    if cut_idx == 0 and cut_fraction > 0:
        cut_idx = 1
    head = entries[:cut_idx]
    tail = entries[cut_idx:]
    archived: list[bytes] = []
    kept_recent: list[bytes] = []
    for e in head:
        if entry_is_recent(e, today, exempt_days):
            kept_recent.append(e)
        else:
            archived.append(e)
    return archived, kept_recent, tail


def make_stub(entry: bytes, archive_filename: str, today: _dt.date) -> bytes:
    """§5 stub: single-line placeholder at original position."""
    name = entry_thread_name(entry)
    stub = (
        f"- [{name}] ✅ ARCHIVED {today.strftime('%Y%m%d')} → "
        f".squad/memory/{archive_filename}\n"
    )
    return stub.encode("utf-8")


def archive_path(today: _dt.date) -> Path:
    return THREADS.parent / f"OPEN_THREADS-archive-{today.strftime('%Y%m%d')}.md"


def atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def atomic_append_with_separator(path: Path, data: bytes, ts: str) -> None:
    """§4: same-day re-pass appends after '\\n---\\n## Archival pass <ts>\\n\\n'.
    First write to a fresh archive omits the separator (no prior content)."""
    cur = path.read_bytes() if path.exists() else b""
    sep = b""
    if cur:
        sep = f"\n---\n## Archival pass {ts}\n\n".encode("utf-8")
    atomic_write(path, cur + sep + data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cut-fraction", type=float, default=0.50,
                    help="oldest fraction of '## Closed' entries to archive "
                         "(default 0.50 per open-threads-archival.md §2)")
    ap.add_argument("--exempt-days", type=int, default=7,
                    help="entries closed within last N days stay live "
                         "(default 7 per §2 exemption)")
    ap.add_argument("--timeout", type=float, default=30.0,
                    help="lock acquisition timeout in seconds")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would happen, do not write")
    args = ap.parse_args()

    if not (0.0 < args.cut_fraction < 1.0):
        sys.stderr.write(
            f"[open-threads-rotate] --cut-fraction must be in (0, 1); "
            f"got {args.cut_fraction}\n"
        )
        return 2
    if args.exempt_days < 0:
        sys.stderr.write(
            f"[open-threads-rotate] --exempt-days must be >= 0; "
            f"got {args.exempt_days}\n"
        )
        return 2

    if not THREADS.exists():
        print(f"[open-threads-rotate] no file at {THREADS}; nothing to do")
        return 0

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if not LOCK.exists() or LOCK.stat().st_size == 0:
        LOCK.write_bytes(b"\0")

    bytes_before = THREADS.stat().st_size
    today = _dt.date.today()

    with LOCK.open("r+b") as lockfh:
        if not trail_append.acquire(lockfh, args.timeout):
            sys.stderr.write(
                f"[open-threads-rotate] could not acquire lock within "
                f"{args.timeout}s\n"
            )
            return 1
        try:
            buf = THREADS.read_bytes()
            prefix, closed_header, entries = split_threads(buf)
            if not closed_header:
                print("[open-threads-rotate] no '## Closed' header found; "
                      "abort to avoid corrupting non-conforming file")
                return 2
            if not entries:
                print("[open-threads-rotate] '## Closed' section has no "
                      f"'- [' entries; no-op (size {bytes_before}B)")
                return 0

            archived, kept_recent, kept_remainder = select_oldest_eligible(
                entries, args.cut_fraction, args.exempt_days, today
            )
            if not archived:
                print(f"[open-threads-rotate] cut_fraction {args.cut_fraction} "
                      f"+ exempt_days {args.exempt_days} produced empty slice "
                      f"across {len(entries)} entries (all in slice were recent); "
                      f"no-op")
                return 0

            arch = archive_path(today)
            arch_name = arch.name
            # Each archived entry leaves a stub at its original position.
            stubs = [make_stub(e, arch_name, today) for e in archived]
            archive_blob = b"".join(archived)

            # Reassemble in original file-position order: stubs interleave with
            # kept_recent at the head (head = first cut_idx entries, by spec §2),
            # then kept_remainder. We preserve the original order within head by
            # walking entries[:cut_idx] and emitting stub-or-original.
            cut_idx = int(len(entries) * args.cut_fraction)
            if cut_idx == 0 and args.cut_fraction > 0:
                cut_idx = 1
            head_reassembled: list[bytes] = []
            archived_iter = iter(stubs)
            kept_recent_iter = iter(kept_recent)
            for e in entries[:cut_idx]:
                if entry_is_recent(e, today, args.exempt_days):
                    head_reassembled.append(next(kept_recent_iter))
                else:
                    head_reassembled.append(next(archived_iter))
            new_threads = (
                prefix
                + closed_header
                + b"".join(head_reassembled)
                + b"".join(kept_remainder)
            )

            ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            summary = (
                f"[open-threads-rotate] entries_before={len(entries)} "
                f"entries_archived={len(archived)} "
                f"entries_kept_recent={len(kept_recent)} "
                f"entries_kept_remainder={len(kept_remainder)} "
                f"bytes_before={bytes_before} bytes_after={len(new_threads)} "
                f"archive={arch_name} "
                f"archive_bytes_appended={len(archive_blob)} "
                f"cut_fraction={args.cut_fraction} "
                f"exempt_days={args.exempt_days}"
            )

            if args.dry_run:
                print(f"[open-threads-rotate] DRY-RUN {summary}")
                return 0

            atomic_append_with_separator(arch, archive_blob, ts)
            atomic_write(THREADS, new_threads)
            print(summary)
            return 0
        finally:
            trail_append.release(lockfh)


if __name__ == "__main__":
    sys.exit(main())
