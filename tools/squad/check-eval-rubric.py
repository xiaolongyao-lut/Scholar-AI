"""Apply .squad/identity/eval-rubric.json to a run-*.json eval artifact.

Consumes the rubric filed round 6 session 073733 (eval-rubric.json schema v0)
and emits per-question per-criterion {pass, witness} so the harness can stop
hard-coding lines 154-156 in run-rag-once.ps1.

Pure stdlib. Zero pip dep. Read-only on .squad/. Net-new file (round 5 brief
074155 self-apply). Does not modify run-rag-once.ps1; that wire-in is task
8dcde2d0 owned by tank-r5 — this script is the upstream definition.

Usage:
    py tools/squad/check-eval-rubric.py [<run-id-or-path>]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUBRIC_PATH = REPO / ".squad" / "identity" / "eval-rubric.json"
EVAL_DIR = REPO / ".squad" / "evaluations"

_PUNT_PATTERNS = [
    r"抱歉.{0,4}我.{0,4}不知道",
    r"无法回答",
    r"需要.{0,4}更多.{0,4}信息",
    r"sorry.{0,4}I.{0,4}don'?t.{0,4}know",
    r"cannot.{0,4}answer",
]


def _load_rubric() -> dict:
    return json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))


def _resolve_eval(arg: str | None) -> Path:
    if arg is None:
        runs = sorted(EVAL_DIR.glob("run-*.json"))
        if not runs:
            raise SystemExit("no run-*.json under .squad/evaluations/")
        return runs[-1]
    p = Path(arg)
    if p.is_file():
        return p
    cand = EVAL_DIR / f"{arg}.json" if not arg.endswith(".json") else EVAL_DIR / arg
    if cand.is_file():
        return cand
    raise SystemExit(f"cannot resolve eval: {arg}")


def _check_http(q: dict) -> tuple[bool, str]:
    s = q.get("http_status")
    return (s == 200, f"http_status={s}")


def _check_citation_triple(q: dict) -> tuple[bool, str]:
    cs = q.get("citations") or []
    if not cs:
        return (False, "citation_count=0")
    missing = [i for i, c in enumerate(cs)
               if not (isinstance(c, dict) and all(c.get(k) for k in ("author", "year", "title")))]
    if missing:
        return (False, f"incomplete_triple_at={missing}")
    return (True, f"citation_count={len(cs)}_all_triples_complete")


def _check_no_punt(q: dict) -> tuple[bool, str]:
    text = q.get("response_text") or ""
    for pat in _PUNT_PATTERNS:
        if re.search(pat, text, flags=re.IGNORECASE):
            return (False, f"punt_match={pat!r}")
    return (True, "no_punt_match")


def _check_quality(q: dict) -> tuple[bool, str]:
    qs = q.get("quality_score")
    if qs is None:
        return (False, "quality_score=null")
    return (bool(qs.get("overall_pass")), f"overall_pass={qs.get('overall_pass')}")


_CHECKERS = {
    "http_2xx": _check_http,
    "citation_triple": _check_citation_triple,
    "no_punt": _check_no_punt,
    "quality_vs_wenxianku": _check_quality,
}


def apply(eval_doc: dict, rubric: dict) -> dict:
    out = []
    for q in eval_doc.get("questions", []):
        criteria = {}
        for c in rubric["criteria"]:
            cid = c["id"]
            checker = _CHECKERS.get(cid)
            if checker is None:
                criteria[cid] = {"pass": False, "witness": "no_checker"}
                continue
            ok, witness = checker(q)
            criteria[cid] = {"pass": ok, "witness": witness}
        all_pass = all(v["pass"] for v in criteria.values())
        out.append({"question": q.get("question"), "all_pass": all_pass, "criteria": criteria})
    summary = {
        "total": len(out),
        "all_pass_count": sum(1 for r in out if r["all_pass"]),
        "per_criterion_pass_count": {
            cid: sum(1 for r in out if r["criteria"].get(cid, {}).get("pass"))
            for cid in _CHECKERS
        },
    }
    return {"rubric_schema": rubric.get("schema_version"),
            "eval_run_id": eval_doc.get("run_id"),
            "questions": out, "summary": summary}


def main(argv: list[str]) -> int:
    rubric = _load_rubric()
    eval_path = _resolve_eval(argv[1] if len(argv) > 1 else None)
    eval_doc = json.loads(eval_path.read_text(encoding="utf-8"))
    result = apply(eval_doc, rubric)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
