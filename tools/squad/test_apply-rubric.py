"""Predicate-level contract tests for tools/squad/apply-rubric.py.

Round-23 brief 150128 self-explore artifact. Off-cluster virgin axis under
tools/squad/*.py (the .squad/tools/* test lane is fully forked).

Source filename has a hyphen, so plain import is illegal — module is loaded
via importlib.util.spec_from_file_location to avoid AST sugar drift.

Coverage targets (companion to the just-claimed test_check-eval-rubric.py;
this exercises the SIBLING applier check_quality returns Optional[bool]
which is a distinct contract from check-eval-rubric's strict bool):

  - check_http_2xx: 200 / 503 / missing
  - check_citation_triple: empty / complete / missing-field / non-dict
  - check_no_punt: clean / Chinese / English / missing
  - check_quality: None tri-state contract (None = N/A pending wire-in)
  - CHECKERS dispatch keys cover the 4 rubric criteria
  - apply(): counts dict shape, n_a aggregation, end-to-end on synthetic eval
  - latest_eval(): SystemExit on empty dir, file return on populated

Pure stdlib. Read-only. Uses TemporaryDirectory + monkeypatch on module
constants ROOT/RUBRIC/EVAL_DIR for hermetic isolation.
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


def _load_module():
    src = Path(__file__).resolve().parent / "apply-rubric.py"
    spec = importlib.util.spec_from_file_location("apply_rubric_under_test", src)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {src}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load_module()


# ---------- Predicate tests ----------

class CheckHttpTests(unittest.TestCase):
    def test_200_true(self):
        self.assertTrue(M.check_http_2xx({"http_status": 200}))

    def test_503_false(self):
        self.assertFalse(M.check_http_2xx({"http_status": 503}))

    def test_missing_false(self):
        self.assertFalse(M.check_http_2xx({}))

    def test_string_status_false(self):
        # equality check only; "200" string should not pass.
        self.assertFalse(M.check_http_2xx({"http_status": "200"}))


class CheckCitationTripleTests(unittest.TestCase):
    def test_empty_list_false(self):
        self.assertFalse(M.check_citation_triple({"citations": []}))

    def test_missing_key_false(self):
        self.assertFalse(M.check_citation_triple({}))

    def test_complete_triple_true(self):
        self.assertTrue(M.check_citation_triple({"citations": [
            {"author": "Smith", "year": 2023, "title": "T1"},
            {"author": "Lee", "year": 2024, "title": "T2"},
        ]}))

    def test_missing_title_false(self):
        self.assertFalse(M.check_citation_triple({"citations": [
            {"author": "S", "year": 2023, "title": "T"},
            {"author": "L", "year": 2024},
        ]}))

    def test_empty_string_field_false(self):
        # Empty string is falsy → triple incomplete.
        self.assertFalse(M.check_citation_triple({"citations": [
            {"author": "", "year": 2023, "title": "T"},
        ]}))

    def test_non_dict_entry_false(self):
        self.assertFalse(M.check_citation_triple({"citations": ["not-a-dict"]}))


class CheckNoPuntTests(unittest.TestCase):
    def test_clean_true(self):
        self.assertTrue(M.check_no_punt({"response_text": "激光熔池关键参数包括功率、扫描速度。"}))

    def test_chinese_punt_false(self):
        self.assertFalse(M.check_no_punt({"response_text": "抱歉我不知道这个问题"}))

    def test_chinese_cant_answer_false(self):
        self.assertFalse(M.check_no_punt({"response_text": "对不起，无法回答"}))

    def test_english_punt_false(self):
        self.assertFalse(M.check_no_punt({"response_text": "sorry I don't know the answer"}))

    def test_cannot_answer_false(self):
        self.assertFalse(M.check_no_punt({"response_text": "We cannot answer this"}))

    def test_missing_text_true(self):
        # No text → no substring match → vacuous True.
        self.assertTrue(M.check_no_punt({}))


class CheckQualityTriStateTests(unittest.TestCase):
    """check_quality returns Optional[bool]: None means "not wired yet"
    (counted under n_a), True/False are real verdicts. This contract differs
    from check-eval-rubric.py's _check_quality (which returns strict bool +
    witness). The applier path is the one wired into the harness."""

    def test_missing_returns_none(self):
        self.assertIsNone(M.check_quality({}))

    def test_overall_pass_true(self):
        self.assertTrue(M.check_quality({"quality_score": {"overall_pass": True}}))

    def test_overall_pass_false(self):
        self.assertFalse(M.check_quality({"quality_score": {"overall_pass": False}}))

    def test_overall_pass_truthy_coerced(self):
        # bool() coercion: non-empty string is truthy.
        self.assertTrue(M.check_quality({"quality_score": {"overall_pass": "yes"}}))


class CheckersDispatchTests(unittest.TestCase):
    def test_dispatch_has_4_canonical_keys(self):
        for cid in ("http_2xx", "citation_triple", "no_punt", "quality_vs_wenxianku"):
            self.assertIn(cid, M.CHECKERS)

    def test_dispatch_size_locked(self):
        # Audit-anchor: any new criterion must come with a decision-trail entry
        # before this test is updated. Fail loudly on silent dispatch growth.
        self.assertEqual(len(M.CHECKERS), 4)


class PuntPatternsTests(unittest.TestCase):
    def test_pattern_count(self):
        self.assertEqual(len(M.PUNT_PATTERNS), 5)

    def test_chinese_present(self):
        joined = "\n".join(M.PUNT_PATTERNS)
        self.assertIn("抱歉", joined)
        self.assertIn("无法回答", joined)
        self.assertIn("需要更多", joined)

    def test_english_present(self):
        joined = "\n".join(M.PUNT_PATTERNS).lower()
        self.assertIn("sorry", joined)
        self.assertIn("cannot answer", joined)


# ---------- End-to-end apply() tests ----------

class ApplyEndToEndTests(unittest.TestCase):
    """apply() reads RUBRIC + eval_path off the module-level constants. We
    monkeypatch RUBRIC by writing into a tmp dir and rebinding M.RUBRIC."""

    def setUp(self):
        self._orig_rubric = M.RUBRIC
        self._tmp = TemporaryDirectory()
        rubric_path = Path(self._tmp.name) / "rubric.json"
        rubric_path.write_text(json.dumps({
            "schema_version": "v0",
            "criteria": [
                {"id": "http_2xx"},
                {"id": "citation_triple"},
                {"id": "no_punt"},
                {"id": "quality_vs_wenxianku"},
            ],
        }), encoding="utf-8")
        M.RUBRIC = rubric_path

    def tearDown(self):
        M.RUBRIC = self._orig_rubric
        self._tmp.cleanup()

    def _write_eval(self, doc: dict) -> Path:
        p = Path(self._tmp.name) / "run-fake.json"
        p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return p

    def test_empty_questions(self):
        eval_path = self._write_eval({"run_id": "abc", "questions": []})
        result = M.apply(eval_path)
        self.assertEqual(result["rubric_schema"], "v0")
        self.assertEqual(result["eval_run_id"], "abc")
        self.assertEqual(result["questions"], [])
        for cid in ("http_2xx", "citation_triple", "no_punt", "quality_vs_wenxianku"):
            self.assertEqual(result["counts"][cid], {"pass": 0, "fail": 0, "n_a": 0})

    def test_perfect_question_aggregates(self):
        eval_path = self._write_eval({"run_id": "ok", "questions": [{
            "question": "Q1",
            "http_status": 200,
            "citations": [{"author": "A", "year": 2023, "title": "T"}],
            "response_text": "A factual response.",
            "quality_score": {"overall_pass": True},
        }]})
        result = M.apply(eval_path)
        self.assertEqual(result["counts"]["http_2xx"]["pass"], 1)
        self.assertEqual(result["counts"]["citation_triple"]["pass"], 1)
        self.assertEqual(result["counts"]["no_punt"]["pass"], 1)
        self.assertEqual(result["counts"]["quality_vs_wenxianku"]["pass"], 1)
        for cid in M.CHECKERS:
            self.assertEqual(result["counts"][cid]["fail"], 0)
            self.assertEqual(result["counts"][cid]["n_a"], 0)

    def test_canonical_503_failure_pattern(self):
        # Mirrors the byte-stable run-20260425-104556 shape: 503 / no cites /
        # no quality_score → http fail, cite fail, punt vacuous-pass, quality n_a.
        eval_path = self._write_eval({"run_id": "blackout", "questions": [{
            "question": "激光熔池流动行为影响，匙孔如何控制？",
            "http_status": 503,
            "citations": [],
            "response_text": "",
            # no quality_score key
        }]})
        result = M.apply(eval_path)
        self.assertEqual(result["counts"]["http_2xx"]["fail"], 1)
        self.assertEqual(result["counts"]["citation_triple"]["fail"], 1)
        self.assertEqual(result["counts"]["no_punt"]["pass"], 1)  # vacuous
        self.assertEqual(result["counts"]["quality_vs_wenxianku"]["n_a"], 1)
        self.assertEqual(result["counts"]["quality_vs_wenxianku"]["pass"], 0)
        self.assertEqual(result["counts"]["quality_vs_wenxianku"]["fail"], 0)


# ---------- latest_eval() tests ----------

class LatestEvalTests(unittest.TestCase):
    def setUp(self):
        self._orig_eval_dir = M.EVAL_DIR
        self._tmp = TemporaryDirectory()
        M.EVAL_DIR = Path(self._tmp.name)

    def tearDown(self):
        M.EVAL_DIR = self._orig_eval_dir
        self._tmp.cleanup()

    def test_empty_dir_raises(self):
        with self.assertRaises(SystemExit) as ctx:
            M.latest_eval()
        self.assertIn("no run-*.json", str(ctx.exception))

    def test_returns_newest_by_mtime(self):
        import os
        import time
        a = M.EVAL_DIR / "run-old.json"
        b = M.EVAL_DIR / "run-new.json"
        a.write_text("{}", encoding="utf-8")
        time.sleep(0.01)  # ensure mtime ordering
        b.write_text("{}", encoding="utf-8")
        # Force older mtime on a in case fs granularity hides it.
        old_t = b.stat().st_mtime - 10
        os.utime(a, (old_t, old_t))
        self.assertEqual(M.latest_eval(), b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
