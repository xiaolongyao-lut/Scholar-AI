#!/usr/bin/env python3
"""test_open_threads_rotate — contract tests for tools/squad/open_threads_rotate.py.

Read-only predicate-level coverage of the pure helpers:
  - split_threads: prefix / closed_header / entries split per §2.
  - entry_is_recent: 7-day exemption per §2 (latest YYYY-MM-DD in first line).
  - entry_thread_name: bracket-name extraction.
  - select_oldest_eligible: cut-fraction × recency-exemption partition.
  - make_stub: §5 single-line archive marker.
  - archive_path: per-day filename shape per §4.
  - atomic_write / atomic_append_with_separator: .tmp+os.replace per §4.7.

Anchors:
  - Spec §4.7 atomic-write hardening.
  - .squad/specs/open-threads-archival.md §2/§4/§5.
  - Round 26 (brief 151345-relabeled-r23) self-explore virgin-axis.
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "open_threads_rotate.py"


def _load():
    repo_root = HERE.parent.parent
    squad_tools = repo_root / ".squad" / "tools"
    if str(squad_tools) not in sys.path:
        sys.path.insert(0, str(squad_tools))
    spec = importlib.util.spec_from_file_location("open_threads_rotate", SRC)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


otr = _load()


class SplitThreadsTests(unittest.TestCase):
    def test_no_closed_header_returns_buf_as_prefix(self):
        buf = b"# Header\n## Active\n- [a] foo\n"
        prefix, hdr, entries = otr.split_threads(buf)
        self.assertEqual(prefix, buf)
        self.assertEqual(hdr, b"")
        self.assertEqual(entries, [])

    def test_basic_split_two_entries(self):
        buf = (
            b"## Active\n- [live] foo\n\n"
            b"## Closed\n\n"
            b"- [old1] closed 2026-04-01\n"
            b"- [old2] closed 2026-04-02\n"
        )
        prefix, hdr, entries = otr.split_threads(buf)
        self.assertIn(b"## Active", prefix)
        self.assertNotIn(b"## Closed", prefix)
        self.assertIn(b"## Closed", hdr)
        self.assertEqual(len(entries), 2)
        self.assertTrue(entries[0].startswith(b"- [old1]"))
        self.assertTrue(entries[1].startswith(b"- [old2]"))

    def test_round_trip_byte_faithful(self):
        buf = (
            b"prelude\n## Active\n- [x] live\n\n"
            b"## Closed\n\n"
            b"- [a] closed 2026-04-01\n  more detail\n"
            b"- [b] closed 2026-04-02\n"
        )
        prefix, hdr, entries = otr.split_threads(buf)
        self.assertEqual(prefix + hdr + b"".join(entries), buf)

    def test_empty_closed_section_has_no_entries(self):
        buf = b"## Active\n- [live] x\n## Closed\n"
        prefix, hdr, entries = otr.split_threads(buf)
        self.assertIn(b"## Closed", hdr)
        self.assertEqual(entries, [])

    def test_indented_continuation_lines_stay_with_entry(self):
        buf = (
            b"## Closed\n"
            b"- [first] closed 2026-04-01\n"
            b"  - sub bullet\n"
            b"  paragraph continuation\n"
            b"- [second] closed 2026-04-02\n"
        )
        _, _, entries = otr.split_threads(buf)
        self.assertEqual(len(entries), 2)
        self.assertIn(b"sub bullet", entries[0])
        self.assertIn(b"paragraph continuation", entries[0])
        self.assertNotIn(b"sub bullet", entries[1])


class EntryIsRecentTests(unittest.TestCase):
    def setUp(self):
        self.today = _dt.date(2026, 4, 25)

    def test_recent_within_7_days(self):
        e = b"- [foo] closed 2026-04-20 -> ok\n"
        self.assertTrue(otr.entry_is_recent(e, self.today, 7))

    def test_old_beyond_7_days(self):
        e = b"- [foo] closed 2026-04-01\n"
        self.assertFalse(otr.entry_is_recent(e, self.today, 7))

    def test_no_date_treated_as_non_recent(self):
        e = b"- [foo] closed long ago\n"
        self.assertFalse(otr.entry_is_recent(e, self.today, 7))

    def test_picks_latest_date_when_multiple(self):
        # First line has both an old and a recent date; uses latest.
        e = b"- [foo] originally 2025-01-01 then closed 2026-04-22\n"
        self.assertTrue(otr.entry_is_recent(e, self.today, 7))

    def test_only_first_line_inspected(self):
        # Recent date on second line should NOT exempt entry.
        e = b"- [foo] closed long ago\n  detail 2026-04-25\n"
        self.assertFalse(otr.entry_is_recent(e, self.today, 7))

    def test_exempt_days_zero_means_nothing_recent(self):
        e = b"- [foo] closed 2026-04-25\n"
        self.assertFalse(otr.entry_is_recent(e, self.today, 0))

    def test_invalid_date_treated_as_non_recent(self):
        # Regex only matches numeric YYYY-MM-DD; invalid month silently rejected.
        e = b"- [foo] closed 2026-13-45\n"
        self.assertFalse(otr.entry_is_recent(e, self.today, 7))


class EntryThreadNameTests(unittest.TestCase):
    def test_basic_name(self):
        self.assertEqual(otr.entry_thread_name(b"- [my-thread] body\n"), "my-thread")

    def test_unicode_name(self):
        # UTF-8 inside brackets must round-trip.
        self.assertEqual(otr.entry_thread_name("- [文档] body\n".encode("utf-8")), "文档")

    def test_no_bracket_returns_unknown(self):
        self.assertEqual(otr.entry_thread_name(b"plain bullet text\n"), "unknown")


class SelectOldestEligibleTests(unittest.TestCase):
    def setUp(self):
        self.today = _dt.date(2026, 4, 25)

    def test_empty_list(self):
        a, kr, t = otr.select_oldest_eligible([], 0.5, 7, self.today)
        self.assertEqual((a, kr, t), ([], [], []))

    def test_basic_50_percent_cut_no_recents(self):
        entries = [
            b"- [a] closed 2026-04-01\n",
            b"- [b] closed 2026-04-02\n",
            b"- [c] closed 2026-04-03\n",
            b"- [d] closed 2026-04-04\n",
        ]
        archived, kept_recent, tail = otr.select_oldest_eligible(entries, 0.5, 7, self.today)
        self.assertEqual(len(archived), 2)
        self.assertEqual(kept_recent, [])
        self.assertEqual(len(tail), 2)
        self.assertTrue(archived[0].startswith(b"- [a]"))
        self.assertTrue(archived[1].startswith(b"- [b]"))
        self.assertTrue(tail[0].startswith(b"- [c]"))

    def test_recent_in_head_kept_not_archived(self):
        # 'b' is recent; should land in kept_recent even though in head slice.
        entries = [
            b"- [a] closed 2026-04-01\n",
            b"- [b] closed 2026-04-22\n",
            b"- [c] closed 2026-04-03\n",
            b"- [d] closed 2026-04-04\n",
        ]
        archived, kept_recent, tail = otr.select_oldest_eligible(entries, 0.5, 7, self.today)
        self.assertEqual(len(archived), 1)
        self.assertTrue(archived[0].startswith(b"- [a]"))
        self.assertEqual(len(kept_recent), 1)
        self.assertTrue(kept_recent[0].startswith(b"- [b]"))
        self.assertEqual(len(tail), 2)

    def test_cut_fraction_zero_archives_nothing(self):
        entries = [b"- [a] closed 2026-04-01\n", b"- [b] closed 2026-04-02\n"]
        archived, kept_recent, tail = otr.select_oldest_eligible(entries, 0.0, 7, self.today)
        self.assertEqual(archived, [])
        self.assertEqual(kept_recent, [])
        self.assertEqual(tail, entries)

    def test_small_list_rounds_up_to_one(self):
        # 1 entry × 0.5 = 0; spec rounds up to 1 when cut_fraction > 0.
        entries = [b"- [only] closed 2026-04-01\n"]
        archived, kept_recent, tail = otr.select_oldest_eligible(entries, 0.5, 7, self.today)
        self.assertEqual(len(archived), 1)
        self.assertEqual(tail, [])

    def test_partition_invariant(self):
        # archived + kept_recent should equal head; tail = remainder; total preserved.
        entries = [b"- [%d]\n" % i for i in range(7)]
        archived, kept_recent, tail = otr.select_oldest_eligible(entries, 0.5, 7, self.today)
        self.assertEqual(len(archived) + len(kept_recent) + len(tail), len(entries))


class MakeStubTests(unittest.TestCase):
    def test_stub_shape(self):
        e = b"- [foo-bar] closed 2026-04-01\n"
        stub = otr.make_stub(e, "OPEN_THREADS-archive-20260425.md", _dt.date(2026, 4, 25))
        self.assertEqual(
            stub,
            "- [foo-bar] ✅ ARCHIVED 20260425 → "
            ".squad/memory/OPEN_THREADS-archive-20260425.md\n".encode("utf-8"),
        )

    def test_stub_handles_unicode_name(self):
        e = "- [文档] closed 2026-04-01\n".encode("utf-8")
        stub = otr.make_stub(e, "X.md", _dt.date(2026, 4, 25))
        self.assertIn("文档".encode("utf-8"), stub)

    def test_stub_with_unparseable_name_uses_unknown(self):
        e = b"plain text no brackets\n"
        stub = otr.make_stub(e, "X.md", _dt.date(2026, 4, 25))
        self.assertIn(b"[unknown]", stub)


class ArchivePathTests(unittest.TestCase):
    def test_archive_path_uses_compact_date(self):
        ap = otr.archive_path(_dt.date(2026, 4, 25))
        self.assertEqual(ap.name, "OPEN_THREADS-archive-20260425.md")

    def test_archive_lives_alongside_threads_file(self):
        ap = otr.archive_path(_dt.date(2026, 4, 25))
        self.assertEqual(ap.parent, otr.THREADS.parent)


class AtomicWriteTests(unittest.TestCase):
    def test_atomic_write_writes_payload(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "out.md"
            otr.atomic_write(target, b"hello")
            self.assertEqual(target.read_bytes(), b"hello")

    def test_atomic_write_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "out.md"
            target.write_bytes(b"OLD")
            otr.atomic_write(target, b"NEW")
            self.assertEqual(target.read_bytes(), b"NEW")

    def test_atomic_write_no_dangling_tmp(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "out.md"
            otr.atomic_write(target, b"x")
            self.assertEqual(sorted(p.name for p in Path(td).iterdir()), ["out.md"])

    def test_append_with_separator_first_write_no_separator(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "arch.md"
            otr.atomic_append_with_separator(target, b"PAYLOAD", "2026-04-25 15:00:00")
            self.assertEqual(target.read_bytes(), b"PAYLOAD")

    def test_append_with_separator_second_write_adds_separator(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "arch.md"
            target.write_bytes(b"FIRST_PASS")
            otr.atomic_append_with_separator(target, b"SECOND_PASS", "2026-04-25 16:00:00")
            content = target.read_bytes()
            self.assertTrue(content.startswith(b"FIRST_PASS"))
            self.assertIn(b"\n---\n## Archival pass 2026-04-25 16:00:00\n\n", content)
            self.assertTrue(content.endswith(b"SECOND_PASS"))


class SourceContractTests(unittest.TestCase):
    """The producer must use .tmp + os.replace per CLAUDE.md §4.7,
    and lock-share semantics must match siblings."""

    def test_source_uses_tmp_staging(self):
        text = SRC.read_text(encoding="utf-8")
        self.assertIn(".tmp", text)

    def test_source_uses_os_replace(self):
        text = SRC.read_text(encoding="utf-8")
        self.assertIn("os.replace(tmp, path)", text)

    def test_source_imports_trail_append_for_lock(self):
        # Reuses trail_append's acquire/release, separate lockfile path.
        text = SRC.read_text(encoding="utf-8")
        self.assertIn("import trail_append", text)

    def test_lockfile_is_sibling_of_open_threads(self):
        self.assertEqual(otr.LOCK.parent, otr.THREADS.parent)
        self.assertEqual(otr.LOCK.name, ".OPEN_THREADS.md.lock")


if __name__ == "__main__":
    unittest.main()
