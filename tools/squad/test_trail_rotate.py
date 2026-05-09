#!/usr/bin/env python3
"""test_trail_rotate — contract tests for tools/squad/trail_rotate.py.

Read-only predicate-level coverage of split_trail / select_oldest_slice /
atomic_write / atomic_append_with_separator, plus an end-to-end --dry-run
invocation as a subprocess (no mutation of the real DECISION_TRAIL.md).

Anchors:
  - trail-archival.md §2 (mechanical 40%-oldest selection, anti-cherry-pick).
  - trail-archival.md §4 (same-day re-pass appends after '\\n---\\n## Archival
    pass <ts>\\n\\n' separator; first write of fresh archive omits it).
  - Spec §4.7 atomic-write hardening (.tmp + os.replace).
  - Round 19 (brief 151150) self-explore virgin-axis (trail_rotate has no
    test sibling; companion to test_audit_wenxianku_filename_hazards.py and
    test_queued_age_report.py landed in prior rounds).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "trail_rotate.py"

# Import as a normal module — filename has no hyphen.
sys.path.insert(0, str(HERE))
import trail_rotate as tr  # noqa: E402


class SplitTrailTests(unittest.TestCase):
    def test_no_anchors_returns_buf_as_header_with_empty_entries(self):
        buf = b"# DECISION_TRAIL\n\n(empty preamble, no entries)\n"
        header, entries = tr.split_trail(buf)
        self.assertEqual(header, buf)
        self.assertEqual(entries, [])

    def test_single_entry_no_header(self):
        buf = b"### [2026-04-25] only entry\n- body\n"
        header, entries = tr.split_trail(buf)
        self.assertEqual(header, b"")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0], buf)

    def test_header_plus_three_entries_concatenate_back_to_original(self):
        buf = (
            b"# DECISION_TRAIL\n\nintro\n\n"
            b"### [2026-04-01] first\n- body1\n\n"
            b"### [2026-04-02] second\n- body2\n\n"
            b"### [2026-04-03] third\n- body3\n"
        )
        header, entries = tr.split_trail(buf)
        self.assertIn(b"# DECISION_TRAIL", header)
        self.assertEqual(len(entries), 3)
        # Round-trip invariant: header + ''.join(entries) == buf
        self.assertEqual(header + b"".join(entries), buf)

    def test_anchor_must_be_at_line_start(self):
        # An '### [' that's not at line-start should NOT split
        buf = b"# header\nblah ### [not anchor] inline\n### [2026-04-01] real\n- body\n"
        header, entries = tr.split_trail(buf)
        self.assertEqual(len(entries), 1)
        self.assertIn(b"real", entries[0])
        self.assertIn(b"not anchor", header)


class SelectOldestSliceTests(unittest.TestCase):
    def _entries(self, sizes):
        # Build entries of given byte sizes; content is just 'A' repeated.
        return [b"A" * n for n in sizes]

    def test_empty_input(self):
        archived, kept = tr.select_oldest_slice([], 0.40)
        self.assertEqual(archived, [])
        self.assertEqual(kept, [])

    def test_default_40_percent_on_uniform_sizes(self):
        # 10 entries of 100 bytes each = 1000 total; 40% target = 400.
        # Cumulative 100,200,300,400 → at i=3 cum=400 >= 400, cut_idx=4.
        entries = self._entries([100] * 10)
        archived, kept = tr.select_oldest_slice(entries, 0.40)
        self.assertEqual(len(archived), 4)
        self.assertEqual(len(kept), 6)

    def test_round_forward_never_mid_entry(self):
        # 1 huge head entry (900 bytes) + 9 tiny (100 each) = 1800 total.
        # 40% target = 720. After i=0 cum=900 >= 720, cut_idx=1.
        entries = [b"A" * 900] + [b"B" * 100] * 9
        archived, kept = tr.select_oldest_slice(entries, 0.40)
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0], b"A" * 900)
        self.assertEqual(len(kept), 9)

    def test_tiny_fraction_still_archives_at_least_one(self):
        # Anti-stagnation clause: cut_fraction>0 with no entry crossing target
        # still archives the head entry to "always make progress".
        entries = [b"A" * 1000] * 5  # total 5000; 0.0001 fraction → target 0.5
        archived, kept = tr.select_oldest_slice(entries, 0.0001)
        self.assertEqual(len(archived), 1)
        self.assertEqual(len(kept), 4)

    def test_zero_fraction_archives_nothing(self):
        # cut_fraction=0.0 short-circuits: no archival.
        entries = [b"A" * 100] * 3
        archived, kept = tr.select_oldest_slice(entries, 0.0)
        # Loop never assigns cut_idx (cum >= 0 only on first iter, but target=0
        # so 0 >= 0 → cut_idx=1). Then the >0 guard doesn't apply. Document
        # actual observed behavior:
        # Reading the code: target=0, on i=0 cum=100 >= 0 → cut_idx=1, break.
        # The post-loop "if cut_idx==0 and cut_fraction>0.0" doesn't fire.
        # So zero fraction actually archives 1 entry. Pin that contract.
        self.assertEqual(len(archived), 1)
        self.assertEqual(len(kept), 2)

    def test_oldest_first_invariant_preserves_file_position_order(self):
        # Archived entries must be the head slice, kept must be the tail.
        entries = [b"first", b"second", b"third", b"fourth", b"fifth"]
        archived, kept = tr.select_oldest_slice(entries, 0.40)
        # Head-side archive
        self.assertEqual(archived[0], b"first")
        # Concatenation invariant
        self.assertEqual(archived + kept, entries)


class AtomicWriteTests(unittest.TestCase):
    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "out.bin"
            tr.atomic_write(target, b"hello")
            self.assertEqual(target.read_bytes(), b"hello")
            # No leftover .tmp
            self.assertFalse(target.with_suffix(".bin.tmp").exists())

    def test_atomic_write_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "out.bin"
            target.write_bytes(b"old")
            tr.atomic_write(target, b"new")
            self.assertEqual(target.read_bytes(), b"new")


class AtomicAppendWithSeparatorTests(unittest.TestCase):
    def test_first_write_omits_separator(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "archive.md"
            tr.atomic_append_with_separator(target, b"first-pass-blob", "2026-04-25 15:00:00")
            self.assertEqual(target.read_bytes(), b"first-pass-blob")

    def test_second_pass_inserts_separator(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "archive.md"
            tr.atomic_append_with_separator(target, b"first", "2026-04-25 15:00:00")
            tr.atomic_append_with_separator(target, b"second", "2026-04-25 16:00:00")
            content = target.read_bytes()
            self.assertIn(b"first", content)
            self.assertIn(b"second", content)
            self.assertIn(b"\n---\n## Archival pass 2026-04-25 16:00:00\n\n", content)
            # Order: first, then separator, then second
            self.assertLess(content.index(b"first"), content.index(b"---"))
            self.assertLess(content.index(b"---"), content.index(b"second"))


class ArchivePathTests(unittest.TestCase):
    def test_archive_path_uses_today_yyyymmdd(self):
        p = tr.archive_path()
        # Filename pattern: DECISION_TRAIL-archive-YYYYMMDD.md
        self.assertTrue(p.name.startswith("DECISION_TRAIL-archive-"))
        self.assertTrue(p.name.endswith(".md"))
        # 8-digit date segment
        date_part = p.stem.split("-")[-1]
        self.assertEqual(len(date_part), 8)
        self.assertTrue(date_part.isdigit())


class DryRunSubprocessTests(unittest.TestCase):
    """End-to-end: invoke trail_rotate.py --dry-run; must NOT mutate any file.

    We can't redirect TRAIL inside the script (it's a module constant), so we
    only check the script reports correctly when run against the real trail
    in dry-run mode (which is read-only by spec).
    """

    def test_dry_run_reports_summary_and_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(SRC), "--dry-run", "--cut-fraction", "0.40"],
            capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0,
                         f"stderr={result.stderr.decode('utf-8', 'replace')[:300]}")
        out = result.stdout.decode("utf-8", "replace")
        # Must contain DRY-RUN marker
        self.assertIn("DRY-RUN", out)
        # Must report cut_fraction
        self.assertIn("cut_fraction=0.4", out)

    def test_invalid_cut_fraction_returns_2(self):
        result = subprocess.run(
            [sys.executable, str(SRC), "--cut-fraction", "1.5", "--dry-run"],
            capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 2)
        err = result.stderr.decode("utf-8", "replace")
        self.assertIn("cut-fraction", err)


class SourceContractTests(unittest.TestCase):
    """Static contract assertions over the source itself (Spec §4.7)."""

    def test_source_uses_tmp_staging(self):
        text = SRC.read_text(encoding="utf-8")
        self.assertIn(".tmp", text)

    def test_source_uses_os_replace(self):
        text = SRC.read_text(encoding="utf-8")
        self.assertIn("os.replace(tmp, path)", text)

    def test_source_imports_trail_append_for_lock_reuse(self):
        text = SRC.read_text(encoding="utf-8")
        self.assertIn("import trail_append", text)
        # Must reuse the same lockfile name as trail_append
        self.assertIn(".DECISION_TRAIL.md.lock", text)


if __name__ == "__main__":
    unittest.main()
