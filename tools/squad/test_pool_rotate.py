#!/usr/bin/env python3
"""test_pool_rotate — contract tests for tools/squad/pool_rotate.py.

Read-only predicate-level coverage of the four pure helpers:
  - split_pool: H2 anchor regex covers BOTH "## [" and "## NN/50" forms
    (round-20 brief 131553 patch documented at L13453-13458 of source).
  - select_kept: newest-first walk, byte-budget invariant, kept order
    is chronological after reverse.
  - archive_path: per-day filename shape.
  - atomic_write / atomic_append: .tmp staging + os.replace per §4.7.

Anchors:
  - Spec §4.7 atomic-write hardening.
  - Goal-drift §4 line 91 (".tmp + replace 原子模式").
  - Round 25 brief 151032 self-explore virgin-axis (eval byte-stable 129m).
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "pool_rotate.py"


def _load():
    # pool_rotate.py imports `pool_append` from .squad/tools — make that
    # importable before exec_module so the source loads cleanly in-test.
    repo_root = HERE.parent.parent
    squad_tools = repo_root / ".squad" / "tools"
    if str(squad_tools) not in sys.path:
        sys.path.insert(0, str(squad_tools))
    spec = importlib.util.spec_from_file_location("pool_rotate", SRC)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pr = _load()


class SplitPoolTests(unittest.TestCase):
    def test_empty_buffer_returns_empty_header_and_no_entries(self):
        header, entries = pr.split_pool(b"")
        self.assertEqual(header, b"")
        self.assertEqual(entries, [])

    def test_no_anchors_returns_whole_buf_as_header(self):
        buf = b"# Pool\n\nsome prose\nno H2 anchors here\n"
        header, entries = pr.split_pool(buf)
        self.assertEqual(header, buf)
        self.assertEqual(entries, [])

    def test_timestamp_anchor_form_is_recognized(self):
        buf = b"# Header\n\n## [2026-04-25T07:06Z] e1\nbody1\n## [2026-04-25T08:00Z] e2\nbody2\n"
        header, entries = pr.split_pool(buf)
        self.assertEqual(header, b"# Header\n\n")
        self.assertEqual(len(entries), 2)
        self.assertTrue(entries[0].startswith(b"## [2026-04-25T07:06Z]"))
        self.assertTrue(entries[1].startswith(b"## [2026-04-25T08:00Z]"))

    def test_score_anchor_form_is_recognized(self):
        # Round-20 patch at H2_RE: "## NN/50" must split too.
        buf = b"# H\n\n## 47/50 first req\nbody\n## 49/50 second\nbody2\n"
        header, entries = pr.split_pool(buf)
        self.assertEqual(header, b"# H\n\n")
        self.assertEqual(len(entries), 2)
        self.assertTrue(entries[0].startswith(b"## 47/50"))
        self.assertTrue(entries[1].startswith(b"## 49/50"))

    def test_mixed_anchor_forms_split_in_order(self):
        buf = (
            b"hdr\n"
            b"## [2026-04-25T01:00Z] ts-form\nbodyA\n"
            b"## 50/50 score-form\nbodyB\n"
            b"## [2026-04-25T02:00Z] ts-form-2\nbodyC\n"
        )
        header, entries = pr.split_pool(buf)
        self.assertEqual(header, b"hdr\n")
        self.assertEqual(len(entries), 3)
        self.assertIn(b"ts-form", entries[0])
        self.assertIn(b"score-form", entries[1])
        self.assertIn(b"ts-form-2", entries[2])

    def test_concatenating_header_plus_entries_round_trips_buffer(self):
        buf = b"H\n## [a]\nx\n## 1/50 b\ny\n## [c]\nz\n"
        header, entries = pr.split_pool(buf)
        self.assertEqual(header + b"".join(entries), buf)

    def test_h2_at_buffer_start_yields_empty_header(self):
        buf = b"## [first] no header\nbody\n"
        header, entries = pr.split_pool(buf)
        self.assertEqual(header, b"")
        self.assertEqual(len(entries), 1)


class SelectKeptTests(unittest.TestCase):
    def test_empty_entries_returns_empty(self):
        archived, kept = pr.select_kept([], 100)
        self.assertEqual(archived, [])
        self.assertEqual(kept, [])

    def test_all_fit_under_budget_archive_is_empty(self):
        entries = [b"a" * 10, b"b" * 10, b"c" * 10]
        archived, kept = pr.select_kept(entries, 100)
        self.assertEqual(archived, [])
        self.assertEqual(kept, entries)

    def test_keeps_newest_when_over_budget(self):
        entries = [b"a" * 50, b"b" * 50, b"c" * 50, b"d" * 50]  # 200 total
        archived, kept = pr.select_kept(entries, 120)
        # Newest-first walk fits c+d (100B) but not b (would be 150B).
        self.assertEqual(kept, [b"c" * 50, b"d" * 50])
        self.assertEqual(archived, [b"a" * 50, b"b" * 50])

    def test_kept_preserves_chronological_order(self):
        # Ordering invariant: kept entries on disk are in original (oldest-to-
        # newest) order, NOT reverse-chronological from the walk.
        entries = [b"OLD", b"MID", b"NEW"]
        _, kept = pr.select_kept(entries, 6)  # only 6 bytes fits 2 of 3
        self.assertEqual(kept, [b"MID", b"NEW"])

    def test_single_oversized_entry_is_kept_anyway(self):
        # Implementation guard: if first newest entry alone exceeds budget,
        # `kept_rev` is still appended on first iteration because the guard
        # `if total + size > keep_bytes and kept_rev:` requires kept_rev to
        # be non-empty before bailing. So newest is always retained.
        entries = [b"old", b"X" * 9999]
        archived, kept = pr.select_kept(entries, 10)
        self.assertEqual(kept, [b"X" * 9999])
        self.assertEqual(archived, [b"old"])

    def test_archive_plus_kept_partitions_entries_exactly(self):
        entries = [b"a" * 30, b"b" * 30, b"c" * 30, b"d" * 30, b"e" * 30]
        archived, kept = pr.select_kept(entries, 70)
        self.assertEqual(archived + kept, entries)


class ArchivePathTests(unittest.TestCase):
    def test_archive_path_uses_today_iso_date(self):
        today = _dt.datetime.now().strftime("%Y-%m-%d")
        ap = pr.archive_path()
        self.assertEqual(
            ap.name, f"requirement-pool-archive-{today}.md"
        )

    def test_archive_path_lives_alongside_pool(self):
        self.assertEqual(pr.archive_path().parent, pr.POOL.parent)


class AtomicWriteTests(unittest.TestCase):
    def test_atomic_write_creates_file_with_payload(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "out.md"
            pr.atomic_write(target, b"hello world")
            self.assertEqual(target.read_bytes(), b"hello world")

    def test_atomic_write_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "out.md"
            target.write_bytes(b"OLD")
            pr.atomic_write(target, b"NEW")
            self.assertEqual(target.read_bytes(), b"NEW")

    def test_atomic_write_leaves_no_dangling_tmp(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "out.md"
            pr.atomic_write(target, b"x")
            siblings = sorted(p.name for p in Path(td).iterdir())
            # only the final file, no .tmp residue
            self.assertEqual(siblings, ["out.md"])

    def test_atomic_append_creates_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "arch.md"
            pr.atomic_append(target, b"first\n")
            self.assertEqual(target.read_bytes(), b"first\n")

    def test_atomic_append_concatenates_existing(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "arch.md"
            target.write_bytes(b"first\n")
            pr.atomic_append(target, b"second\n")
            self.assertEqual(target.read_bytes(), b"first\nsecond\n")


class SourceContractTests(unittest.TestCase):
    """The producer must use .tmp + os.replace per CLAUDE.md §4.7."""

    def test_source_uses_tmp_staging(self):
        text = SRC.read_text(encoding="utf-8")
        self.assertIn(".tmp", text)

    def test_source_uses_os_replace(self):
        text = SRC.read_text(encoding="utf-8")
        self.assertIn("os.replace(tmp, path)", text)

    def test_source_imports_pool_append_for_lock(self):
        # Lock-path corrigendum b6dfea69: rotation MUST share the lockfile
        # path with pool_append, achieved by importing the module.
        text = SRC.read_text(encoding="utf-8")
        self.assertIn("import pool_append", text)

    def test_h2_regex_covers_both_anchor_forms(self):
        text = SRC.read_text(encoding="utf-8")
        self.assertIn(r"^## (?:\[|[0-9]+/50)", text)


if __name__ == "__main__":
    unittest.main()
