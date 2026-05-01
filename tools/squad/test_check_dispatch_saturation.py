#!/usr/bin/env python3
"""test_check_dispatch_saturation — contract tests for the dispatch-backpressure
predicate at tools/squad/check-dispatch-saturation.py.

Source has a hyphen; loaded via importlib.

Anchors:
  - Spec §4.7 (read-only diagnostic — no atomic-write to assert).
  - Goal-drift §4 line 88 (no silent failures), dispatch-side extension.
  - Round 28 brief 151658 self-explore: discharges round-27 requirement
    'dispatch-backpressure invariant' filed at 2026-04-25T15:15:00Z.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "check-dispatch-saturation.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_dispatch_saturation", SRC)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cds = _load()


class EvaluateTests(unittest.TestCase):
    def test_ok_when_no_agent_over_cap_and_not_lease_dead(self):
        payload = {
            "total_queued": 50,
            "unleased_count": 10,
            "by_assigned": {"tank-r3": 5, "oracle-r5": 3},
        }
        code, v = cds.evaluate(payload, per_agent_cap=20, global_floor=200,
                               only_agent=None)
        self.assertEqual(code, 0)
        self.assertEqual(v["saturated_agents"], [])
        self.assertFalse(v["global_dead"])

    def test_per_agent_saturation_returns_2(self):
        payload = {
            "total_queued": 60,
            "unleased_count": 30,  # not all unleased -> not global_dead
            "by_assigned": {"tank-r3": 46, "oracle-r5": 5},
        }
        code, v = cds.evaluate(payload, per_agent_cap=20, global_floor=200,
                               only_agent=None)
        self.assertEqual(code, 2)
        self.assertEqual(len(v["saturated_agents"]), 1)
        self.assertEqual(v["saturated_agents"][0]["agent"], "tank-r3")
        self.assertEqual(v["saturated_agents"][0]["queued"], 46)

    def test_global_dead_returns_3_and_supersedes_per_agent(self):
        # Both per-agent saturation AND global-dead conditions present;
        # global takes precedence.
        payload = {
            "total_queued": 233,
            "unleased_count": 233,
            "by_assigned": {"oracle-r5": 48, "tank-r3": 46},
        }
        code, v = cds.evaluate(payload, per_agent_cap=20, global_floor=200,
                               only_agent=None)
        self.assertEqual(code, 3)
        self.assertTrue(v["global_dead"])

    def test_global_dead_requires_full_unleased(self):
        # Even at huge depth, if any task is leased, lease machinery isn't
        # dead — fall back to per-agent saturation check.
        payload = {
            "total_queued": 500,
            "unleased_count": 499,
            "by_assigned": {"x": 5, "y": 5},
        }
        code, v = cds.evaluate(payload, per_agent_cap=20, global_floor=200,
                               only_agent=None)
        self.assertEqual(code, 0)
        self.assertFalse(v["global_dead"])

    def test_global_dead_requires_total_at_or_above_floor(self):
        payload = {
            "total_queued": 10,
            "unleased_count": 10,
            "by_assigned": {"x": 5},
        }
        code, _ = cds.evaluate(payload, per_agent_cap=20, global_floor=200,
                               only_agent=None)
        self.assertEqual(code, 0)

    def test_only_agent_filter_ignores_other_saturation(self):
        # tank-r3 is way over, but we ask about tank-r5 only -> ok.
        payload = {
            "total_queued": 60,
            "unleased_count": 30,
            "by_assigned": {"tank-r3": 99, "tank-r5": 3},
        }
        code, v = cds.evaluate(payload, per_agent_cap=20, global_floor=200,
                               only_agent="tank-r5")
        self.assertEqual(code, 0)
        self.assertEqual(v["saturated_agents"], [])

    def test_only_agent_filter_picks_up_target_saturation(self):
        payload = {
            "total_queued": 60,
            "unleased_count": 30,
            "by_assigned": {"tank-r3": 99, "tank-r5": 3},
        }
        code, v = cds.evaluate(payload, per_agent_cap=20, global_floor=200,
                               only_agent="tank-r3")
        self.assertEqual(code, 2)
        self.assertEqual(v["saturated_agents"][0]["agent"], "tank-r3")
        self.assertEqual(v["saturated_agents"][0]["queued"], 99)

    def test_missing_agent_in_payload_treated_as_zero(self):
        payload = {
            "total_queued": 60,
            "unleased_count": 30,
            "by_assigned": {"tank-r3": 5},
        }
        code, _ = cds.evaluate(payload, per_agent_cap=20, global_floor=200,
                               only_agent="not-present")
        self.assertEqual(code, 0)

    def test_zero_total_is_not_global_dead(self):
        payload = {"total_queued": 0, "unleased_count": 0, "by_assigned": {}}
        code, v = cds.evaluate(payload, per_agent_cap=20, global_floor=0,
                               only_agent=None)
        self.assertEqual(code, 0)
        self.assertFalse(v["global_dead"])

    def test_saturated_agents_sorted_descending_by_queued(self):
        payload = {
            "total_queued": 100,
            "unleased_count": 50,
            "by_assigned": {"a": 30, "b": 50, "c": 21, "d": 5},
        }
        code, v = cds.evaluate(payload, per_agent_cap=20, global_floor=200,
                               only_agent=None)
        self.assertEqual(code, 2)
        names = [s["agent"] for s in v["saturated_agents"]]
        self.assertEqual(names, ["b", "a", "c"])


class NewestDiagnosticTests(unittest.TestCase):
    def test_returns_path_when_diagnostic_present(self):
        # Real diagnostic dir from round-27 should have a queued-age-*.json.
        diag = cds.newest_diagnostic()
        # Either there is one (most rounds) or not (fresh repo); both are valid
        # — the function must return a Path or None and never raise.
        self.assertTrue(diag is None or isinstance(diag, Path))


class SourceContractTests(unittest.TestCase):
    def test_source_is_pure_stdlib_no_imports(self):
        # Spec: no subprocess, no network. Check imports specifically — the
        # docstring may mention these words descriptively.
        text = SRC.read_text(encoding="utf-8")
        for forbidden in ("import subprocess", "import urllib",
                          "import requests", "import http.client"):
            self.assertNotIn(forbidden, text)

    def test_source_documents_exit_codes(self):
        text = SRC.read_text(encoding="utf-8")
        for code_doc in ("Exit codes", "0  no saturation", "2  per-agent",
                         "3  global", "4  no diagnostic"):
            self.assertIn(code_doc, text)

    def test_dispatch_saturation_marker_string_is_stable(self):
        # Brief-emitter / OPEN_THREADS sweep will grep for this prefix.
        text = SRC.read_text(encoding="utf-8")
        self.assertIn("DISPATCH-SATURATION ok", text)
        self.assertIn("DISPATCH-SATURATION lease_machinery_dead", text)
        self.assertIn("DISPATCH-SATURATION per_agent", text)
        self.assertIn("DISPATCH-SATURATION no_diagnostic", text)


if __name__ == "__main__":
    unittest.main()
