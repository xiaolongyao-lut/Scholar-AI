"""Compare per-criterion pass/fail between two run-*.json files via apply-rubric.

Pure stdlib. No LLM. No network. Closes goal-drift §5 line 100 observability gap
("连续 3 轮通过率不降") with a mechanical per-criterion delta report.

Usage:
    py tools/squad/diff-rubric.py <run-old.json> <run-new.json>
Exit: 0 always (delta report goes to stdout JSON).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPLIER = ROOT / "tools" / "squad" / "apply-rubric.py"


def load_applier():
    spec = importlib.util.spec_from_file_location("apply_rubric", APPLIER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def diff_runs(old_path: Path, new_path: Path) -> dict:
    ar = load_applier()
    old = ar.apply(old_path)
    new = ar.apply(new_path)
    crit_ids = list(old["counts"].keys())
    out = {
        "old_run_id": old["eval_run_id"],
        "new_run_id": new["eval_run_id"],
        "per_criterion_delta": {},
        "per_question_changes": [],
    }
    for cid in crit_ids:
        o = old["counts"][cid]
        n = new["counts"][cid]
        out["per_criterion_delta"][cid] = {
            "old": o,
            "new": n,
            "pass_delta": n["pass"] - o["pass"],
            "fail_delta": n["fail"] - o["fail"],
            "n_a_delta": n["n_a"] - o["n_a"],
        }
    # Per-question changes (assumes same question order; 4 canonical questions are
    # stable per goal-drift §2).
    for i, (oq, nq) in enumerate(zip(old["questions"], new["questions"])):
        flips = {}
        for cid in crit_ids:
            if oq[cid] != nq[cid]:
                flips[cid] = {"old": oq[cid], "new": nq[cid]}
        if flips:
            out["per_question_changes"].append({
                "index": i,
                "question": nq.get("question") or oq.get("question"),
                "flips": flips,
            })
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: py diff-rubric.py <run-old.json> <run-new.json>", file=sys.stderr)
        return 2
    result = diff_runs(Path(argv[1]), Path(argv[2]))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
