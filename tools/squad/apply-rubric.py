"""Mechanical rubric applier: read .squad/identity/eval-rubric.json + a run-*.json,
emit per-question per-criterion pass/fail. Pure stdlib. No LLM. No network.

Usage:
    py tools/squad/apply-rubric.py [run_json_path]
    (default = latest .squad/evaluations/run-*.json)
Exit code: 0 = applier itself succeeded; pass_rate is in stdout JSON.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUBRIC = ROOT / ".squad" / "identity" / "eval-rubric.json"
EVAL_DIR = ROOT / ".squad" / "evaluations"

PUNT_PATTERNS = [
    "抱歉我不知道", "无法回答", "需要更多信息",
    "sorry I don't know", "cannot answer",
]


def latest_eval() -> Path:
    files = sorted(EVAL_DIR.glob("run-*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise SystemExit("no run-*.json found")
    return files[-1]


def check_http_2xx(q: dict) -> bool:
    return q.get("http_status") == 200


def check_citation_triple(q: dict) -> bool:
    cites = q.get("citations") or []
    if not cites:
        return False
    for c in cites:
        if not isinstance(c, dict):
            return False
        if not (c.get("author") and c.get("year") and c.get("title")):
            return False
    return True


def check_no_punt(q: dict) -> bool:
    text = q.get("response_text") or ""
    return not any(p in text for p in PUNT_PATTERNS)


def check_quality(q: dict) -> bool | None:
    # Requires quality_heuristic wire-in (task 8dcde2d0). Until then, return None.
    qs = q.get("quality_score")
    if qs is None:
        return None
    return bool(qs.get("overall_pass"))


CHECKERS = {
    "http_2xx": check_http_2xx,
    "citation_triple": check_citation_triple,
    "no_punt": check_no_punt,
    "quality_vs_wenxianku": check_quality,
}


def apply(eval_path: Path) -> dict:
    rubric = json.loads(RUBRIC.read_text(encoding="utf-8"))
    eval_data = json.loads(eval_path.read_text(encoding="utf-8"))
    out = {
        "rubric_schema": rubric["schema_version"],
        "eval_run_id": eval_data.get("run_id"),
        "questions": [],
    }
    counts = {c["id"]: {"pass": 0, "fail": 0, "n_a": 0} for c in rubric["criteria"]}
    for q in eval_data.get("questions", []):
        per = {"question": q.get("question")}
        for crit in rubric["criteria"]:
            cid = crit["id"]
            res = CHECKERS[cid](q)
            per[cid] = res
            if res is None:
                counts[cid]["n_a"] += 1
            elif res:
                counts[cid]["pass"] += 1
            else:
                counts[cid]["fail"] += 1
        out["questions"].append(per)
    out["counts"] = counts
    return out


def main(argv: list[str]) -> int:
    eval_path = Path(argv[1]) if len(argv) > 1 else latest_eval()
    result = apply(eval_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
