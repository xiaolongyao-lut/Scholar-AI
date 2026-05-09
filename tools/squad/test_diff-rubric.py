"""Contract tests for tools/squad/diff-rubric.py.

Pins per-criterion arithmetic (pass/fail/n_a delta), per-question flip
detection, stable-question-order assumption, sibling-import path discipline,
and main() usage/exit contract. Pure stdlib + pytest, no subprocess, no LLM.

Goal-drift anchor: §5 line 100 ("连续 3 轮通过率不降") observability —
locking the diff vocabulary so future refactors cannot silently change
delta semantics.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIFF_RUBRIC = ROOT / "tools" / "squad" / "diff-rubric.py"


def _load_diff_rubric():
    spec = importlib.util.spec_from_file_location("diff_rubric_under_test", DIFF_RUBRIC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def dr():
    return _load_diff_rubric()


# ------------------------------------------------------------------ shape


def test_module_exposes_diff_runs(dr):
    assert callable(dr.diff_runs)


def test_module_exposes_main(dr):
    assert callable(dr.main)


def test_applier_path_is_sibling(dr):
    # APPLIER must point at the canonical apply-rubric.py one dir up + tools/squad/.
    assert dr.APPLIER.name == "apply-rubric.py"
    assert dr.APPLIER.parent.name == "squad"
    assert dr.APPLIER.parent.parent.name == "tools"


def test_root_is_repo_root(dr):
    # ROOT is computed as parents[2] of diff-rubric.py — verify it resolves
    # to the repo root (must contain .squad/ and tools/).
    assert (dr.ROOT / ".squad").is_dir()
    assert (dr.ROOT / "tools").is_dir()


# ----------------------------------------------------------------- arithmetic


def _fake_apply_factory(payload_by_path):
    """Return a function suitable for monkeypatching ar.apply.

    payload_by_path: dict[Path, dict] returned by .apply() per call.
    """
    def _apply(path):
        return payload_by_path[Path(path)]
    return _apply


def test_per_criterion_delta_arithmetic(dr, monkeypatch, tmp_path):
    old_path = tmp_path / "run-old.json"
    new_path = tmp_path / "run-new.json"
    old_path.write_text("{}", encoding="utf-8")
    new_path.write_text("{}", encoding="utf-8")

    fake_apply = _fake_apply_factory({
        old_path: {
            "eval_run_id": "OLD",
            "counts": {
                "C1": {"pass": 2, "fail": 1, "n_a": 1},
                "C2": {"pass": 0, "fail": 4, "n_a": 0},
            },
            "questions": [
                {"question": "q0", "C1": "pass", "C2": "fail"},
                {"question": "q1", "C1": "fail", "C2": "fail"},
            ],
        },
        new_path: {
            "eval_run_id": "NEW",
            "counts": {
                "C1": {"pass": 4, "fail": 0, "n_a": 0},
                "C2": {"pass": 1, "fail": 3, "n_a": 0},
            },
            "questions": [
                {"question": "q0", "C1": "pass", "C2": "pass"},
                {"question": "q1", "C1": "pass", "C2": "fail"},
            ],
        },
    })

    fake_ar = type("M", (), {"apply": staticmethod(fake_apply)})
    monkeypatch.setattr(dr, "load_applier", lambda: fake_ar)

    out = dr.diff_runs(old_path, new_path)

    assert out["old_run_id"] == "OLD"
    assert out["new_run_id"] == "NEW"
    assert out["per_criterion_delta"]["C1"]["pass_delta"] == 2
    assert out["per_criterion_delta"]["C1"]["fail_delta"] == -1
    assert out["per_criterion_delta"]["C1"]["n_a_delta"] == -1
    assert out["per_criterion_delta"]["C2"]["pass_delta"] == 1
    assert out["per_criterion_delta"]["C2"]["fail_delta"] == -1
    assert out["per_criterion_delta"]["C2"]["n_a_delta"] == 0


def test_per_criterion_delta_carries_old_and_new(dr, monkeypatch, tmp_path):
    """The delta entry must echo the raw old/new dicts so downstream
    auditors do not have to reload the runs."""
    p1, p2 = tmp_path / "a.json", tmp_path / "b.json"
    p1.write_text("{}", encoding="utf-8")
    p2.write_text("{}", encoding="utf-8")
    fake_apply = _fake_apply_factory({
        p1: {"eval_run_id": "A", "counts": {"X": {"pass": 1, "fail": 2, "n_a": 3}}, "questions": []},
        p2: {"eval_run_id": "B", "counts": {"X": {"pass": 4, "fail": 5, "n_a": 6}}, "questions": []},
    })
    monkeypatch.setattr(dr, "load_applier", lambda: type("M", (), {"apply": staticmethod(fake_apply)}))
    out = dr.diff_runs(p1, p2)
    assert out["per_criterion_delta"]["X"]["old"] == {"pass": 1, "fail": 2, "n_a": 3}
    assert out["per_criterion_delta"]["X"]["new"] == {"pass": 4, "fail": 5, "n_a": 6}


# ----------------------------------------------------------------- flips


def test_per_question_changes_records_flips_only(dr, monkeypatch, tmp_path):
    p1, p2 = tmp_path / "a.json", tmp_path / "b.json"
    p1.write_text("{}", encoding="utf-8")
    p2.write_text("{}", encoding="utf-8")
    fake_apply = _fake_apply_factory({
        p1: {
            "eval_run_id": "A",
            "counts": {"C1": {"pass": 0, "fail": 0, "n_a": 0}},
            "questions": [
                {"question": "q0", "C1": "pass"},
                {"question": "q1", "C1": "fail"},
            ],
        },
        p2: {
            "eval_run_id": "B",
            "counts": {"C1": {"pass": 0, "fail": 0, "n_a": 0}},
            "questions": [
                {"question": "q0", "C1": "pass"},  # unchanged
                {"question": "q1", "C1": "pass"},  # flipped fail->pass
            ],
        },
    })
    monkeypatch.setattr(dr, "load_applier", lambda: type("M", (), {"apply": staticmethod(fake_apply)}))
    out = dr.diff_runs(p1, p2)

    # Only the flipped question is reported.
    assert len(out["per_question_changes"]) == 1
    chg = out["per_question_changes"][0]
    assert chg["index"] == 1
    assert chg["question"] == "q1"
    assert chg["flips"] == {"C1": {"old": "fail", "new": "pass"}}


def test_per_question_changes_empty_when_no_flips(dr, monkeypatch, tmp_path):
    p1, p2 = tmp_path / "a.json", tmp_path / "b.json"
    p1.write_text("{}", encoding="utf-8")
    p2.write_text("{}", encoding="utf-8")
    same_q = [{"question": "q0", "C1": "pass"}]
    fake_apply = _fake_apply_factory({
        p1: {"eval_run_id": "A", "counts": {"C1": {"pass": 1, "fail": 0, "n_a": 0}}, "questions": same_q},
        p2: {"eval_run_id": "B", "counts": {"C1": {"pass": 1, "fail": 0, "n_a": 0}}, "questions": list(same_q)},
    })
    monkeypatch.setattr(dr, "load_applier", lambda: type("M", (), {"apply": staticmethod(fake_apply)}))
    out = dr.diff_runs(p1, p2)
    assert out["per_question_changes"] == []


def test_question_text_falls_back_to_old(dr, monkeypatch, tmp_path):
    """If new[i]['question'] is missing/empty, the report should fall back to old[i]['question']."""
    p1, p2 = tmp_path / "a.json", tmp_path / "b.json"
    p1.write_text("{}", encoding="utf-8")
    p2.write_text("{}", encoding="utf-8")
    fake_apply = _fake_apply_factory({
        p1: {"eval_run_id": "A", "counts": {"C1": {"pass": 0, "fail": 0, "n_a": 0}},
             "questions": [{"question": "OLD-TEXT", "C1": "fail"}]},
        p2: {"eval_run_id": "B", "counts": {"C1": {"pass": 0, "fail": 0, "n_a": 0}},
             "questions": [{"question": None, "C1": "pass"}]},
    })
    monkeypatch.setattr(dr, "load_applier", lambda: type("M", (), {"apply": staticmethod(fake_apply)}))
    out = dr.diff_runs(p1, p2)
    assert out["per_question_changes"][0]["question"] == "OLD-TEXT"


def test_zip_truncates_to_shortest_question_list(dr, monkeypatch, tmp_path):
    """diff_runs uses zip(old, new) — extra trailing questions are silently
    ignored. Pin this so a future change to itertools.zip_longest is a
    visible breaking change, not a silent one."""
    p1, p2 = tmp_path / "a.json", tmp_path / "b.json"
    p1.write_text("{}", encoding="utf-8")
    p2.write_text("{}", encoding="utf-8")
    fake_apply = _fake_apply_factory({
        p1: {"eval_run_id": "A", "counts": {"C1": {"pass": 0, "fail": 0, "n_a": 0}},
             "questions": [{"question": "q0", "C1": "pass"}]},
        p2: {"eval_run_id": "B", "counts": {"C1": {"pass": 0, "fail": 0, "n_a": 0}},
             "questions": [
                 {"question": "q0", "C1": "fail"},
                 {"question": "q1-extra", "C1": "fail"},
             ]},
    })
    monkeypatch.setattr(dr, "load_applier", lambda: type("M", (), {"apply": staticmethod(fake_apply)}))
    out = dr.diff_runs(p1, p2)
    # Only the index-0 flip is reported; the extra index-1 entry is dropped.
    assert [c["index"] for c in out["per_question_changes"]] == [0]


# ----------------------------------------------------------------- main contract


def test_main_usage_returns_2(dr, capsys):
    rc = dr.main(["diff-rubric.py"])  # missing both args
    assert rc == 2
    err = capsys.readouterr().err
    assert "usage" in err.lower()


def test_main_too_many_args_returns_2(dr, capsys):
    rc = dr.main(["diff-rubric.py", "a.json", "b.json", "c.json"])
    assert rc == 2


def test_main_returns_0_on_success_and_emits_json(dr, monkeypatch, tmp_path, capsys):
    p1, p2 = tmp_path / "a.json", tmp_path / "b.json"
    p1.write_text("{}", encoding="utf-8")
    p2.write_text("{}", encoding="utf-8")
    fake_apply = _fake_apply_factory({
        p1: {"eval_run_id": "A", "counts": {"C1": {"pass": 0, "fail": 0, "n_a": 0}}, "questions": []},
        p2: {"eval_run_id": "B", "counts": {"C1": {"pass": 0, "fail": 0, "n_a": 0}}, "questions": []},
    })
    monkeypatch.setattr(dr, "load_applier", lambda: type("M", (), {"apply": staticmethod(fake_apply)}))
    rc = dr.main(["diff-rubric.py", str(p1), str(p2)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    # JSON envelope keys are stable.
    assert set(payload.keys()) == {
        "old_run_id", "new_run_id", "per_criterion_delta", "per_question_changes",
    }
    assert payload["old_run_id"] == "A"
    assert payload["new_run_id"] == "B"


# ------------------------------------------------------------------ purity


def test_diff_runs_does_not_write_to_disk(dr, monkeypatch, tmp_path):
    """Spec §4.7 atomic-write doesn't apply because diff_runs is read-only.
    Pin that no files are created in the per-call workdir."""
    p1, p2 = tmp_path / "a.json", tmp_path / "b.json"
    p1.write_text("{}", encoding="utf-8")
    p2.write_text("{}", encoding="utf-8")
    fake_apply = _fake_apply_factory({
        p1: {"eval_run_id": "A", "counts": {}, "questions": []},
        p2: {"eval_run_id": "B", "counts": {}, "questions": []},
    })
    monkeypatch.setattr(dr, "load_applier", lambda: type("M", (), {"apply": staticmethod(fake_apply)}))
    before = set(tmp_path.iterdir())
    dr.diff_runs(p1, p2)
    after = set(tmp_path.iterdir())
    assert before == after  # no side-effects in tmp_path
