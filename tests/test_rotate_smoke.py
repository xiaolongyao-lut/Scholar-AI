"""Smoke tests for tools/squad/pool_rotate.py + tools/squad/trail_rotate.py.

Discharges .squad/specs/rotate-trigger-policy.md A7 followup
("smoke test the full round-trip ... requires a non-production
trail+pool fixture, since live trail is currently 472K tokens and a
real rotation pass would be a one-shot decision").

Strategy: import the rotate modules and exercise their PURE functions
(split_*, select_*, atomic_write, atomic_append_with_separator) with
synthetic byte buffers. Does NOT invoke main() — main() resolves
TRAIL/POOL paths from __file__ at module import and would target the
live files. Pure-function coverage is sufficient to verify:

  1. split_*: header + entries decomposition is round-trip lossless
     (header + b"".join(entries) == original).
  2. select_*: mechanical-cut invariants per spec §2 (no entry split,
     no cherry-pick, byte-budget honored).
  3. atomic_write: temp+replace lands target atomically; partial
     state never observable on disk.
  4. atomic_append_with_separator: trail-archival.md §4 separator
     ('\\n---\\n## Archival pass <ts>\\n\\n') prepended only on
     non-empty target.

Runtime: < 100ms. No network, no live-file mutation, no lock acquisition
(lock paths live elsewhere in main()).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "squad"))

# Importing pool_append/trail_append happens transitively. They reside
# in .squad/tools/, which the rotate modules sys.path.insert at import.
import pool_rotate  # noqa: E402
import trail_rotate  # noqa: E402


# ---------- shared fixture builders ----------

def _build_synthetic_trail(n_entries: int) -> bytes:
    """Build a synthetic DECISION_TRAIL.md-shaped buffer with N entries.

    Each entry follows the canonical '### [' header pattern. Sizes vary
    so byte-position cuts produce non-trivial slices.
    """
    header = b"# DECISION_TRAIL\n\nSynthetic fixture for smoke test.\n\n"
    parts = [header]
    for i in range(n_entries):
        body_size = 100 + (i % 7) * 50  # 100..400 bytes per entry
        body = b"x" * body_size
        parts.append(
            f"### [2026-04-25 13:{i:02d} UTC+8 round {i} brief synthetic] entry {i}\n".encode()
            + b"- pass_rate: 0.0\n- new_reqs: 0\n- artifact: none\n"
            + body
            + b"\n\n"
        )
    return b"".join(parts)


def _build_synthetic_pool(n_entries: int) -> bytes:
    """Build a synthetic requirement-pool.md-shaped buffer with N entries."""
    header = b"# requirement-pool\n\nSynthetic fixture.\n\n"
    parts = [header]
    for i in range(n_entries):
        body = b"y" * (200 + (i % 5) * 80)
        parts.append(
            f"## [2026-04-25 round {i} synthetic] {i:02d}/50 fixture-axis-{i}\n".encode()
            + b"- status: needs-score\n- evidence: synthetic\n"
            + body
            + b"\n\n"
        )
    return b"".join(parts)


# ---------- trail_rotate pure-function tests ----------

def test_split_trail_roundtrip_lossless():
    buf = _build_synthetic_trail(10)
    header, entries = trail_rotate.split_trail(buf)
    assert len(entries) == 10
    assert header + b"".join(entries) == buf
    # Each entry starts with the canonical anchor.
    for e in entries:
        assert e.startswith(b"### [")


def test_split_trail_no_anchors_returns_entries_empty():
    """A non-conforming trail (no '### [') returns ([], header=full_buf).

    main() handles this by aborting with exit code 2; the pure function
    just needs to signal it via len(entries) == 0.
    """
    buf = b"# trail with no entries\n\njust prose.\n"
    header, entries = trail_rotate.split_trail(buf)
    assert entries == []
    assert header == buf


def test_select_oldest_slice_40pct_default():
    """trail-archival.md §2 mechanical 40%-oldest cut.

    10 entries × 200 bytes = 2000 bytes total. target = 800. Loop walks
    entries[i] accumulating cum; breaks the FIRST time cum >= target,
    setting cut_idx = i + 1. So:
      i=0 cum=200; i=1 cum=400; i=2 cum=600; i=3 cum=800 → break,
      cut_idx = 4. Archived = entries[:4] (4 entries), kept = entries[4:]
      (6 entries). Mechanical: first crossing wins, no rounding-up.
    """
    entries = [b"a" * 200 for _ in range(10)]
    archived, kept = trail_rotate.select_oldest_slice(entries, 0.40)
    assert len(archived) == 4
    assert len(kept) == 6
    # Anti-cherry-pick: archived must be the OLDEST (head) slice.
    assert archived == entries[:4]
    assert kept == entries[4:]
    # Boundary discipline: no entry split.
    assert b"".join(archived) + b"".join(kept) == b"".join(entries)


def test_select_oldest_slice_empty_input_returns_empty():
    archived, kept = trail_rotate.select_oldest_slice([], 0.40)
    assert archived == [] and kept == []


def test_select_oldest_slice_tiny_fraction_archives_at_least_one():
    """Edge: cut_fraction so small no entry crosses target.

    Per spec/code edge-case clause: 'archive the head entry only (still
    oldest-by-position; preserves "always make progress")'.
    """
    entries = [b"x" * 1000 for _ in range(5)]  # 5000 bytes total
    archived, kept = trail_rotate.select_oldest_slice(entries, 0.0001)
    assert len(archived) == 1  # head entry, mechanically chosen
    assert archived[0] == entries[0]
    assert len(kept) == 4


def test_atomic_write_lands_target(tmp_path):
    target = tmp_path / "out.md"
    trail_rotate.atomic_write(target, b"hello world\n")
    assert target.read_bytes() == b"hello world\n"
    # No .tmp orphan should remain.
    assert not (tmp_path / "out.md.tmp").exists()


def test_atomic_append_with_separator_first_write_no_separator(tmp_path):
    target = tmp_path / "archive.md"
    trail_rotate.atomic_append_with_separator(target, b"PAYLOAD\n", "2026-04-25 13:04:00")
    out = target.read_bytes()
    # First write: no separator prepended.
    assert out == b"PAYLOAD\n"
    assert b"---" not in out
    assert b"Archival pass" not in out


def test_atomic_append_with_separator_second_write_inserts_separator(tmp_path):
    target = tmp_path / "archive.md"
    trail_rotate.atomic_append_with_separator(target, b"FIRST\n", "2026-04-25 13:04:00")
    trail_rotate.atomic_append_with_separator(target, b"SECOND\n", "2026-04-25 13:05:00")
    out = target.read_bytes()
    # trail-archival.md §4: '\n---\n## Archival pass <ts>\n\n' between passes.
    assert out.startswith(b"FIRST\n")
    assert b"\n---\n## Archival pass 2026-04-25 13:05:00\n\n" in out
    assert out.endswith(b"SECOND\n")


# ---------- pool_rotate pure-function tests ----------

def test_split_pool_roundtrip_lossless():
    buf = _build_synthetic_pool(8)
    header, entries = pool_rotate.split_pool(buf)
    assert len(entries) == 8
    assert header + b"".join(entries) == buf
    for e in entries:
        assert e.startswith(b"## [")


def test_select_kept_keeps_newest_under_budget():
    """pool_rotate.select_kept walks NEWEST-first, accumulating until the
    next entry would exceed keep_bytes. Keeps the tail (newest); archives
    the head (oldest).
    """
    entries = [b"e" * 100 for _ in range(10)]  # 1000 bytes total
    # Budget = 350 → fits 3 entries (300 bytes); the 4th would push to 400 > 350.
    archived, kept = pool_rotate.select_kept(entries, 350)
    assert len(kept) == 3  # newest 3
    assert kept == entries[7:]
    assert len(archived) == 7  # oldest 7
    assert archived == entries[:7]


def test_select_kept_all_fit_returns_no_archive():
    entries = [b"e" * 100 for _ in range(5)]  # 500 bytes total
    archived, kept = pool_rotate.select_kept(entries, 1000)
    # All fit. select_kept returns ([], all_entries).
    assert archived == []
    assert kept == entries


def test_pool_atomic_append_creates_then_extends(tmp_path):
    target = tmp_path / "pool-archive.md"
    pool_rotate.atomic_append(target, b"ALPHA\n")
    pool_rotate.atomic_append(target, b"BETA\n")
    # Pool archive uses bare append (no separator — spec §4 of pool-archival
    # is more lenient than trail's, multiple passes per day to same file).
    assert target.read_bytes() == b"ALPHA\nBETA\n"


# ---------- end-to-end synthetic round-trip ----------

def test_trail_rotate_synthetic_e2e(tmp_path, monkeypatch):
    """Full round-trip on synthetic trail. Verifies kept+archived
    concatenation reproduces the input exactly (byte-perfect rotation
    is the load-bearing invariant per trail-archival.md §4 'verbatim
    copy ... no rewrites').
    """
    buf = _build_synthetic_trail(20)
    header, entries = trail_rotate.split_trail(buf)
    archived, kept = trail_rotate.select_oldest_slice(entries, 0.40)

    # Simulate atomic execution: write archive, write new trail.
    archive_target = tmp_path / "DECISION_TRAIL-archive-20260425.md"
    new_trail_target = tmp_path / "DECISION_TRAIL.md"

    trail_rotate.atomic_append_with_separator(
        archive_target, b"".join(archived), "2026-04-25 13:04:00"
    )
    trail_rotate.atomic_write(new_trail_target, header + b"".join(kept))

    # Byte-perfect invariant: archive + kept-with-header reconstructs the
    # original trail (modulo the §4 separator that's only in the archive,
    # which on FIRST write is empty).
    archive_bytes = archive_target.read_bytes()
    new_trail_bytes = new_trail_target.read_bytes()
    # Reconstruct: header + archived + kept == original buf.
    reconstructed = header + archive_bytes + b"".join(kept)
    assert reconstructed == buf

    # Sanity: new trail is strictly smaller than input (rotation made progress).
    assert len(new_trail_bytes) < len(buf)
    # Sanity: archive holds at least 30% of original entries (40% target,
    # mechanical cut may round forward to next anchor).
    assert len(archived) >= int(0.30 * len(entries))


def test_pool_rotate_synthetic_e2e(tmp_path):
    """Full round-trip on synthetic pool. Same byte-perfect invariant."""
    buf = _build_synthetic_pool(15)
    header, entries = pool_rotate.split_pool(buf)
    # keep ~40% of bytes (analog of trail's archival fraction; pool spec
    # uses --keep-bytes absolute, not a fraction, so we pick a value that
    # exercises non-empty archived + non-empty kept).
    total_entry_bytes = sum(len(e) for e in entries)
    keep_budget = int(total_entry_bytes * 0.40)
    archived, kept = pool_rotate.select_kept(entries, keep_budget)
    assert archived and kept  # both sides non-empty for a meaningful test

    archive_target = tmp_path / "requirement-pool-archive-2026-04-25.md"
    new_pool_target = tmp_path / "requirement-pool.md"
    pool_rotate.atomic_append(archive_target, b"".join(archived))
    pool_rotate.atomic_write(new_pool_target, header + b"".join(kept))

    # Byte-perfect: header + archived + kept == buf.
    reconstructed = header + archive_target.read_bytes() + b"".join(kept)
    assert reconstructed == buf
    # Newest-first kept: the LAST entry of the input must be in kept.
    assert entries[-1] == kept[-1]
    # Oldest-first archived: the FIRST entry of the input must be in archived.
    assert entries[0] == archived[0]
