#!/usr/bin/env python3
"""test_rubric_history — contract tests for tools/squad/rubric-history.py.

Read-only predicate-level coverage of aggregate() time-series shape, the
fail-closed exception path (per profile v3 §2.3 fail-closed), and the
mkstemp + os.replace atomic-write contract. Source has hyphens; loaded
via importlib.

Anchors:
  - Spec §4.7 atomic-write hardening (.tmp + os.replace).
  - Profile v3 §2.3 fail-closed: per-run apply() exceptions become
    timeline entries with {run, error}, not silent drops.
  - Round 24 brief 151206 self-explore virgin-axis (rubric-history.py had
    no test sibling; companion to test_audit_wenxianku_filename_hazards.py
    landed previously).
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SRC = HERE / "rubric-history.py"


def _load():
    spec = importlib.util.spec_from_file_location("rubric_history", SRC)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rh = _load()


def _make_run(dirpath: Path, name: str, mtime: float) -> Path:
    p = dirpath / name
    p.write_text("{}", encoding="utf-8")
    import os as _os
    _os.utime(p, (mtime, mtime))
    return p


class AggregateTests(unittest.TestCase):
    def test_empty_dir_returns_zero_runs(self):
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td)
            with mock.patch.object(rh, "EVAL_DIR", empty):
                with mock.patch.object(rh, "_load_applier", return_value=mock.MagicMock()):
                    out = rh.aggregate()
        self.assertEqual(out["n_runs"], 0)
        self.assertEqual(out["n_questions_total"], 0)
        self.assertEqual(out["timeline"], [])
        self.assertEqual(out["schema_version"], "v0")

    def test_runs_sorted_by_mtime_ascending(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _make_run(d, "run-c.json", 3000)
            _make_run(d, "run-a.json", 1000)
            _make_run(d, "run-b.json", 2000)
            fake_applier = mock.MagicMock()
            fake_applier.apply.return_value = {
                "questions": [], "counts": {},
            }
            with mock.patch.object(rh, "EVAL_DIR", d):
                with mock.patch.object(rh, "_load_applier", return_value=fake_applier):
                    out = rh.aggregate()
        names = [t["run"] for t in out["timeline"]]
        self.assertEqual(names, ["run-a.json", "run-b.json", "run-c.json"])
        # mtimes monotonically nondecreasing
        mtimes = [t["mtime_unix"] for t in out["timeline"]]
        self.assertEqual(mtimes, sorted(mtimes))

    def test_totals_sum_pass_across_runs(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _make_run(d, "run-1.json", 1000)
            _make_run(d, "run-2.json", 2000)
            fake = mock.MagicMock()
            fake.apply.side_effect = [
                {"questions": [{}, {}, {}, {}], "counts": {
                    "http_2xx": {"pass": 4}, "citation_triple": {"pass": 1},
                    "no_punt": {"pass": 4}, "quality_vs_wenxianku": {"pass": 0}}},
                {"questions": [{}, {}, {}, {}], "counts": {
                    "http_2xx": {"pass": 0}, "citation_triple": {"pass": 0},
                    "no_punt": {"pass": 4}, "quality_vs_wenxianku": {"pass": 1}}},
            ]
            with mock.patch.object(rh, "EVAL_DIR", d):
                with mock.patch.object(rh, "_load_applier", return_value=fake):
                    out = rh.aggregate()
        self.assertEqual(out["n_runs"], 2)
        self.assertEqual(out["n_questions_total"], 8)
        self.assertEqual(out["totals_pass"]["http_2xx"], 4)
        self.assertEqual(out["totals_pass"]["citation_triple"], 1)
        self.assertEqual(out["totals_pass"]["no_punt"], 8)
        self.assertEqual(out["totals_pass"]["quality_vs_wenxianku"], 1)

    def test_apply_exception_becomes_timeline_error_not_raise(self):
        """Profile v3 §2.3 fail-closed — per-run failures must be recorded, not silent."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _make_run(d, "run-good.json", 1000)
            _make_run(d, "run-bad.json",  2000)
            fake = mock.MagicMock()
            fake.apply.side_effect = [
                {"questions": [{}], "counts": {"http_2xx": {"pass": 1}}},
                RuntimeError("boom-deliberate-test"),
            ]
            with mock.patch.object(rh, "EVAL_DIR", d):
                with mock.patch.object(rh, "_load_applier", return_value=fake):
                    out = rh.aggregate()
        self.assertEqual(out["n_runs"], 2)
        timeline = out["timeline"]
        self.assertEqual(len(timeline), 2)
        # Good run carries counts; bad run carries error
        self.assertIn("counts", timeline[0])
        self.assertNotIn("error", timeline[0])
        self.assertIn("error", timeline[1])
        self.assertIn("boom-deliberate-test", timeline[1]["error"])
        # Totals do NOT include the failed run
        self.assertEqual(out["totals_pass"]["http_2xx"], 1)

    def test_unknown_counter_id_propagates_into_totals(self):
        """totals.get(cid, 0) defaults — new counter ids must not crash."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _make_run(d, "run-x.json", 1000)
            fake = mock.MagicMock()
            fake.apply.return_value = {
                "questions": [{}],
                "counts": {"future_metric": {"pass": 7}},
            }
            with mock.patch.object(rh, "EVAL_DIR", d):
                with mock.patch.object(rh, "_load_applier", return_value=fake):
                    out = rh.aggregate()
        self.assertEqual(out["totals_pass"].get("future_metric"), 7)


class AtomicWriteTests(unittest.TestCase):
    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "out.json"
            rh._atomic_write(target, '{"k": 1}')
            self.assertTrue(target.exists())
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["k"], 1)

    def test_atomic_write_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "out.json"
            target.write_text('"old"', encoding="utf-8")
            rh._atomic_write(target, '"new"')
            self.assertEqual(target.read_text(encoding="utf-8"), '"new"')

    def test_atomic_write_no_tmp_leftover_on_success(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "out.json"
            rh._atomic_write(target, '{}')
            leftovers = [p.name for p in Path(td).iterdir() if p.name.endswith(".tmp")]
            self.assertEqual(leftovers, [])


class SourceContractTests(unittest.TestCase):
    """Static contract assertions over the source itself."""

    def test_source_uses_os_replace(self):
        text = SRC.read_text(encoding="utf-8")
        self.assertIn("os.replace(tmp, path)", text)

    def test_source_uses_mkstemp_with_tmp_suffix(self):
        text = SRC.read_text(encoding="utf-8")
        self.assertIn('suffix=".tmp"', text)
        self.assertIn("tempfile.mkstemp", text)

    def test_source_uses_run_glob_pattern(self):
        text = SRC.read_text(encoding="utf-8")
        self.assertIn('glob("run-*.json")', text)

    def test_source_declares_v0_schema(self):
        text = SRC.read_text(encoding="utf-8")
        self.assertIn('"schema_version": "v0"', text)


if __name__ == "__main__":
    unittest.main()
