#!/usr/bin/env python3
"""test_audit_wenxianku_filename_hazards — contract tests for
tools/squad/audit-wenxianku-filename-hazards.py.

Read-only predicate-level coverage of the three hazard detectors (H1/H2/H3),
the report renderer's verdict branching, and the .tmp + os.replace atomic-write
contract. Source filename has hyphens; loaded via importlib.

Anchors:
  - Spec §4.7 atomic-write hardening (.tmp + os.replace).
  - Goal-drift §3 line 29 + §3.3 wenxianku as quality benchmark.
  - Round 23 (brief 150933) self-explore virgin-axis (audit_wenxianku has
    no test sibling; companion to test_queued_age_report.py landed previously).
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SRC = HERE / "audit-wenxianku-filename-hazards.py"


def _load():
    spec = importlib.util.spec_from_file_location("audit_wxk", SRC)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


awxk = _load()


class ScanTests(unittest.TestCase):
    def test_missing_dir_returns_empty_list(self):
        bogus = HERE / "_does_not_exist_wxk_dir"
        self.assertFalse(bogus.exists())
        self.assertEqual(awxk.scan(bogus), [])

    def test_h1_fullwidth_pipe_detected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "IJHMT2025｜华中科技大学.pdf").write_bytes(b"%PDF-")
            (p / "clean_name.pdf").write_bytes(b"%PDF-")
            rows = awxk.scan(p)
        flags = {r["name"]: r["h1_fullwidth_pipe"] for r in rows}
        self.assertTrue(flags["IJHMT2025｜华中科技大学.pdf"])
        self.assertFalse(flags["clean_name.pdf"])

    def test_h2_trailing_dots_one_two_three(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "one.pdf").write_bytes(b"%PDF-")
            (p / "stem.dotdot..pdf").write_bytes(b"%PDF-")
            rows = awxk.scan(p)
        flags = {r["name"]: r["h2_trailing_dots"] for r in rows}
        # 'one.pdf' stem='one' — no trailing dot before extension
        self.assertFalse(flags["one.pdf"])
        # 'stem.dotdot..pdf' stem='stem.dotdot.' ends with '.'
        self.assertTrue(flags["stem.dotdot..pdf"])

    def test_h3_bare_I_delimiter(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "IJHMT2025 I 华中科技大学.pdf").write_bytes(b"%PDF-")
            (p / "Inside one word.pdf").write_bytes(b"%PDF-")
            rows = awxk.scan(p)
        flags = {r["name"]: r["h3_bare_I_delimiter"] for r in rows}
        self.assertTrue(flags["IJHMT2025 I 华中科技大学.pdf"])
        # 'Inside' is a longer token; bare 'I' is NOT a token here
        self.assertFalse(flags["Inside one word.pdf"])

    def test_skips_non_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "real.pdf").write_bytes(b"%PDF-")
            (p / "subdir").mkdir()
            rows = awxk.scan(p)
        names = [r["name"] for r in rows]
        self.assertIn("real.pdf", names)
        self.assertNotIn("subdir", names)

    def test_exists_via_path_control(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "real.pdf").write_bytes(b"%PDF-")
            rows = awxk.scan(p)
        self.assertTrue(rows[0]["exists_via_path"])


class RenderReportTests(unittest.TestCase):
    def test_clean_verdict_when_no_hazards(self):
        rows = [{
            "name": "clean.pdf",
            "h1_fullwidth_pipe": False,
            "h2_trailing_dots": False,
            "h3_bare_I_delimiter": False,
            "exists_via_path": True,
        }]
        out = awxk.render_report(rows)
        self.assertIn("All filenames clean", out)
        self.assertIn("ccf57765", out)

    def test_dirty_verdict_when_any_hazard(self):
        rows = [{
            "name": "dirty｜name.pdf",
            "h1_fullwidth_pipe": True,
            "h2_trailing_dots": False,
            "h3_bare_I_delimiter": False,
            "exists_via_path": True,
        }]
        out = awxk.render_report(rows)
        self.assertIn("Hazards present", out)
        self.assertIn("normalization", out)
        # Recommended normalizations should mention all three hazards
        self.assertIn("H1", out)
        self.assertIn("H2", out)
        self.assertIn("H3", out)

    def test_long_names_truncated_in_table(self):
        long_name = "a" * 80 + ".pdf"
        rows = [{
            "name": long_name,
            "h1_fullwidth_pipe": False,
            "h2_trailing_dots": False,
            "h3_bare_I_delimiter": False,
            "exists_via_path": True,
        }]
        out = awxk.render_report(rows)
        self.assertIn("...", out)
        # Full long name must NOT appear verbatim (truncation kicks in)
        self.assertNotIn(long_name, out)

    def test_summary_counts_match_input(self):
        rows = [
            {"name": "a.pdf", "h1_fullwidth_pipe": True,  "h2_trailing_dots": False, "h3_bare_I_delimiter": False, "exists_via_path": True},
            {"name": "b.pdf", "h1_fullwidth_pipe": True,  "h2_trailing_dots": True,  "h3_bare_I_delimiter": False, "exists_via_path": True},
            {"name": "c.pdf", "h1_fullwidth_pipe": False, "h2_trailing_dots": False, "h3_bare_I_delimiter": True,  "exists_via_path": False},
        ]
        out = awxk.render_report(rows)
        self.assertIn("H1 fullwidth-pipe `｜` count: **2/3**", out)
        self.assertIn("H2 trailing-dots before .pdf: **1/3**", out)
        self.assertIn("H3 bare-`I` delimiter token: **1/3**", out)
        self.assertIn("Path.exists() control: **2/3**", out)


class AtomicWriteTests(unittest.TestCase):
    def test_atomic_write_creates_file_with_content(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "sub" / "out.md"
            awxk.atomic_write(target, "hello\n")
            self.assertTrue(target.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), "hello\n")
            # No leftover .tmp
            self.assertFalse(target.with_suffix(".md.tmp").exists())

    def test_atomic_write_overwrites_existing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "out.md"
            target.write_text("old", encoding="utf-8")
            awxk.atomic_write(target, "new")
            self.assertEqual(target.read_text(encoding="utf-8"), "new")


class SourceContractTests(unittest.TestCase):
    """Static contract assertions over the source itself."""

    def test_source_uses_tmp_staging(self):
        text = SRC.read_text(encoding="utf-8")
        self.assertIn(".tmp", text)

    def test_source_uses_os_replace(self):
        text = SRC.read_text(encoding="utf-8")
        self.assertIn("os.replace(tmp, path)", text)

    def test_source_declares_fullwidth_pipe_constant(self):
        self.assertEqual(awxk.FULLWIDTH_PIPE, "｜")


if __name__ == "__main__":
    unittest.main()
