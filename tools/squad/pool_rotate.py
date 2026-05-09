#!/usr/bin/env python3
"""Rotate .squad/identity/requirement-pool.md when it grows past a soft cap.

Sibling of .squad/tools/pool_append.py. Authored under squad task
9189a3bd-a058-4819-b0e3-0d80e609613d (42/50, "pool-archive-split-v0")
with lock-path corrigendum b6dfea69-448f-4357-a824-fc8fd1047212 (41/50).

Why this exists
---------------
pool_append.py grows requirement-pool.md without bound. Eight-plus pool
entries across rounds 9-13 (2026-04-25) cited a "500KB rotation
trigger" -- but no code enforced it. Real-time observation at 10:18:55
confirmed the pool crossed 500_000 bytes with zero rotation. By round
13 the pool was 579_707 bytes, growing ~8-14 KB/min from parallel-
Morpheus traffic. Eventually every Read of the pool becomes a latency
hit, and msvcrt LK_NBLCK byte-range locks contend with themselves.

What this does (v0)
-------------------
1. Reads requirement-pool.md (under the SAME lockfile pool_append.py
   uses, so concurrent appenders block).
2. Splits the file into:
   - header (lines 1..first H2 anchor minus 1, kept verbatim),
   - entries (each block starting at "^## [" up to the next H2),
   - keeps the most recent entries that fit under --keep-bytes,
   - archives the rest to requirement-pool-archive-<YYYY-MM-DD>.md
     (append; multiple rotations per day go to the same archive).
3. Writes both files atomically (.tmp + os.replace), inside the same
   single critical section.
4. Prints a one-line SUMMARY.

Lock primitive
--------------
Imports acquire/release from pool_append.py verbatim. The lockfile path
is .squad/identity/.requirement-pool.md.lock -- the SAME path
pool_append.py uses (this is the entire point of corrigendum b6dfea69:
prior rotation proposals cited divergent paths, none of which would
have mutually-excluded an in-flight pool_append.py writer).

Usage
-----
    py -3 tools/squad/pool_rotate.py [--keep-bytes 200000] [--dry-run]
                                     [--timeout 30]

Exit codes
----------
0 success (or no-op if pool already under --keep-bytes)
1 lock acquisition failed
2 unrecoverable (header parse failure, etc.)
"""
from __future__ import annotations
import argparse
import datetime as _dt
import os
import re
import sys
from pathlib import Path

# Reuse the lock primitive verbatim from pool_append.py. We import the
# module rather than copy-paste the helpers so any future hardening of
# acquire()/release() lands in both tools simultaneously.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".squad" / "tools"))
import pool_append  # type: ignore[import-not-found]

POOL = ROOT / ".squad" / "identity" / "requirement-pool.md"
LOCK = POOL.parent / ".requirement-pool.md.lock"  # MATCHES pool_append.py:37

# H2 anchor pattern. Pool entries start with "## [" (timestamp form,
# typical of older entries) OR "## NN/50" (score form, dominant for
# requirement-pool primary filings since the 50-point rubric landed —
# see L13453-13458 documenting the defect this regex addresses, and
# L13486 acceptance #1 specifying this exact patch). Splitting only on
# "## [" missed all "## NN/50" entries and produced silently-mis-bounded
# archive slices on rotation. Round-20 brief 131553 morpheus-self patch
# discharging L13488 Acceptance #1 (the one-line code-fix lane that
# remained open after rounds 18-19 discharged #2/#3/#4).
H2_RE = re.compile(rb"(?m)^## (?:\[|[0-9]+/50)")


def split_pool(buf: bytes) -> tuple[bytes, list[bytes]]:
    """Return (header_bytes, [entry_bytes, ...]).

    Header = everything before the first "^## [" anchor. Each entry
    begins at an anchor line and runs up to (but not including) the
    next anchor. Trailing newlines are preserved on each entry.
    """
    matches = list(H2_RE.finditer(buf))
    if not matches:
        return buf, []
    header = buf[: matches[0].start()]
    entries: list[bytes] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(buf)
        entries.append(buf[m.start() : end])
    return header, entries


def select_kept(entries: list[bytes], keep_bytes: int) -> tuple[list[bytes], list[bytes]]:
    """Return (archived_entries, kept_entries).

    Walks entries from newest (last) backwards, accumulating bytes
    until adding the next would exceed keep_bytes. Newest-first
    ordering means the returned kept list is ALSO newest-first; we
    reverse it before writing so on-disk order stays chronological.
    """
    kept_rev: list[bytes] = []
    total = 0
    cutoff = len(entries)
    for i in range(len(entries) - 1, -1, -1):
        size = len(entries[i])
        if total + size > keep_bytes and kept_rev:
            cutoff = i + 1
            break
        kept_rev.append(entries[i])
        total += size
        cutoff = i
    archived = entries[:cutoff]
    kept = entries[cutoff:]
    return archived, kept


def archive_path() -> Path:
    today = _dt.datetime.now().strftime("%Y-%m-%d")
    return POOL.parent / f"requirement-pool-archive-{today}.md"


def atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def atomic_append(path: Path, data: bytes) -> None:
    """Append-or-create with atomic semantics: read existing, concat, replace."""
    cur = path.read_bytes() if path.exists() else b""
    atomic_write(path, cur + data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-bytes", type=int, default=200_000,
                    help="target size for active pool after rotation (default 200000)")
    ap.add_argument("--timeout", type=float, default=30.0,
                    help="lock acquisition timeout in seconds (default 30)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would happen, do not write")
    args = ap.parse_args()

    if not POOL.exists():
        print(f"[pool-rotate] no pool at {POOL}; nothing to do")
        return 0

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if not LOCK.exists() or LOCK.stat().st_size == 0:
        LOCK.write_bytes(b"\0")

    bytes_before = POOL.stat().st_size
    if bytes_before <= args.keep_bytes and not args.dry_run:
        print(f"[pool-rotate] pool {bytes_before}B <= keep_bytes "
              f"{args.keep_bytes}; no-op")
        return 0

    with LOCK.open("r+b") as lockfh:
        if not pool_append.acquire(lockfh, args.timeout):
            sys.stderr.write(
                f"[pool-rotate] could not acquire lock within "
                f"{args.timeout}s\n"
            )
            return 1
        try:
            buf = POOL.read_bytes()
            header, entries = split_pool(buf)
            if not entries:
                print(f"[pool-rotate] no H2 anchors found; abort to avoid "
                      f"corrupting non-conforming pool")
                return 2
            archived, kept = select_kept(entries, args.keep_bytes)
            if not archived:
                print(f"[pool-rotate] all {len(entries)} entries fit under "
                      f"{args.keep_bytes}B; no-op (size {bytes_before}B)")
                return 0

            new_pool = header + b"".join(kept)
            archive_blob = b"".join(archived)
            arch = archive_path()

            summary = (
                f"[pool-rotate] entries_before={len(entries)} "
                f"entries_archived={len(archived)} entries_kept={len(kept)} "
                f"bytes_before={bytes_before} bytes_after={len(new_pool)} "
                f"archive={arch.name} archive_bytes_appended={len(archive_blob)}"
            )

            if args.dry_run:
                print(f"[pool-rotate] DRY-RUN {summary}")
                return 0

            # Single critical section: archive append + pool rewrite both
            # land before lock release. Reader after release sees either
            # both old or both new -- never half-rotated.
            atomic_append(arch, archive_blob)
            atomic_write(POOL, new_pool)
            print(summary)
            return 0
        finally:
            pool_append.release(lockfh)


if __name__ == "__main__":
    sys.exit(main())
