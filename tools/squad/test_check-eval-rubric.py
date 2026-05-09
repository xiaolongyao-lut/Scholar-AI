#!/usr/bin/env python3
"""test_check-eval-rubric.py — predicate-level contract tests for check-eval-rubric.py.

Goal-drift anchor: §4 line 88 (no silent failure) + §3.2 line 76 (citation auditing).
Source: round 22 brief 150124 virgin-axis discharge (eval-rubric lane in tools/squad/,
distinct from saturated .squad/tools/ cluster).

The source filename has a hyphen, so we load via importlib.util.spec_from_file_location
rather than `import check-eval-rubric`. Tests are pure-stdlib + unittest, no pytest.
Read-only against fixture data; never touches real .squad/identity/ or .squad/evaluations/.
"""
from __future__ import annotations
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "check-eval-rubric.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_eval_rubric_mod", SRC)
    assert spec and spec.loader, f"cannot load {SRC}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CheckHttpTests(unittest.TestCase):
    def setUp(self):
        self.m = _load()

    def test_http_pass_when_200(self):
        ok, detail = self.m._check_http({"http_status": 200})
        self.assertTrue(ok)
        self.assertEqual(detail, "http_status=200")

    def test_http_fail_when_500(self):
        ok, detail = self.m._check_http({"http_status": 500})
        self.assertFalse(ok)

    def test_http_fail_when_503(self):
        ok, detail = self.m._check_http({"http_status": 503})
        self.assertFalse(ok)

    def test_http_handles_missing_key(self):
        # Should not raise; returns False.
        ok, _ = self.m._check_http({})
        self.assertFalse(ok)


class CheckCitationTripleTests(unittest.TestCase):
    def setUp(self):
        self.m = _load()

    def test_triple_citation_passes(self):
        q = {
            "citations": [
                {"author": "Smith", "year": 2023, "title": "A"},
                {"author": "Jones", "year": 2024, "title": "B"},
            ]
        }
        ok, detail = self.m._check_citation_triple(q)
        self.assertTrue(ok)
        self.assertEqual(detail, "citation_count=2_all_triples_complete")

    def test_incomplete_citation_fails(self):
        q = {"citations": [{"author": "Smith", "year": 2023}]}
        ok, detail = self.m._check_citation_triple(q)
        self.assertFalse(ok)
        self.assertIn("incomplete_triple_at=[0]", detail)

    def test_zero_citations_fails(self):
        q = {"citations": []}
        ok, detail = self.m._check_citation_triple(q)
        self.assertFalse(ok)
        self.assertEqual(detail, "citation_count=0")


class CheckNoPuntTests(unittest.TestCase):
    def setUp(self):
        self.m = _load()

    def test_substantive_answer_passes(self):
        q = {"response_text": "Laser keyhole control depends on melt-pool dynamics and beam profile."}
        ok, _ = self.m._check_no_punt(q)
        self.assertTrue(ok)

    def test_chinese_punt_detected(self):
        q = {"response_text": "抱歉，我不知道。"}
        ok, _ = self.m._check_no_punt(q)
        self.assertFalse(ok)

    def test_english_punt_detected(self):
        q = {"response_text": "Sorry, I don't know."}
        ok, _ = self.m._check_no_punt(q)
        self.assertFalse(ok)

    def test_cannot_answer_punt_detected(self):
        q = {"response_text": "无法回答这个问题。"}
        ok, _ = self.m._check_no_punt(q)
        self.assertFalse(ok)


class CheckersDispatchTests(unittest.TestCase):
    def setUp(self):
        self.m = _load()

    def test_checkers_dispatch_has_known_keys(self):
        # _CHECKERS must be a dict mapping criterion id -> callable.
        self.assertIsInstance(self.m._CHECKERS, dict)
        self.assertGreater(len(self.m._CHECKERS), 0)
        for k, v in self.m._CHECKERS.items():
            self.assertTrue(callable(v), f"checker {k!r} must be callable")

    def test_punt_patterns_compiled(self):
        # _PUNT_PATTERNS must be a non-empty iterable of regex patterns.
        self.assertTrue(hasattr(self.m, "_PUNT_PATTERNS"))
        self.assertGreater(len(self.m._PUNT_PATTERNS), 0)


class CheckQualityTests(unittest.TestCase):
    def setUp(self):
        self.m = _load()

    def test_quality_pass_when_overall_pass_true(self):
        ok, detail = self.m._check_quality({"quality_score": {"overall_pass": True}})
        self.assertTrue(ok)
        self.assertEqual(detail, "overall_pass=True")

    def test_quality_fails_when_missing(self):
        ok, detail = self.m._check_quality({})
        self.assertFalse(ok)
        self.assertIn("quality_score=null", detail)


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.m = _load()

    def test_apply_returns_summary_with_counts(self):
        run = {
            "run_id": "run-test",
            "questions": [
                {
                    "question": "q1",
                    "http_status": 200,
                    "response_text": "ok with citations",
                    "citations": [{"author": "A", "year": 2020, "title": "T"}],
                    "quality_score": {"overall_pass": True},
                },
                {
                    "question": "q2",
                    "http_status": 503,
                    "response_text": "抱歉，我不知道",
                    "citations": [],
                    "quality_score": {"overall_pass": False},
                },
            ]
        }
        rubric = {
            "schema_version": "v0",
            "criteria": [
                {"id": "http_2xx", "weight": 1},
                {"id": "no_punt", "weight": 1},
                {"id": "citation_triple", "weight": 1},
                {"id": "quality_vs_wenxianku", "weight": 1},
            ],
        }
        result = self.m.apply(run, rubric)
        self.assertIn("summary", result)
        self.assertIn("questions", result)
        self.assertEqual(result["eval_run_id"], "run-test")
        self.assertEqual(len(result["questions"]), 2)
        # First passes every current criterion; second fails every current criterion.
        self.assertEqual(result["summary"].get("all_pass_count"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
