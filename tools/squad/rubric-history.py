"""Aggregate apply-rubric.py output across the full eval corpus.

Reads every .squad/evaluations/run-*.json, applies the rubric to each,
emits a single time-series JSON to stdout (and optionally writes
.squad/evaluations/rubric-history-<ts>.json atomically).

Pure stdlib. No LLM. No network. Net-new round-5 self-applied artifact.
Imports apply-rubric.py without modifying it (consumer of round-4 074329 product).

Usage:
    py tools/squad/rubric-history.py             # stdout only
    py tools/squad/rubric-history.py --write     # also atomic-write artifact
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / ".squad" / "evaluations"
APPLIER = ROOT / "tools" / "squad" / "apply-rubric.py"


def _load_applier():
    """Import apply-rubric.py as a module without copying its code."""
    spec = importlib.util.spec_from_file_location("_apply_rubric", APPLIER)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import {APPLIER}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def aggregate() -> dict:
    applier = _load_applier()
    runs = sorted(EVAL_DIR.glob("run-*.json"), key=lambda p: p.stat().st_mtime)
    timeline = []
    totals = {"http_2xx": 0, "citation_triple": 0, "no_punt": 0, "quality_vs_wenxianku": 0}
    n_questions = 0
    for run_path in runs:
        try:
            r = applier.apply(run_path)
        except Exception as exc:  # fail-closed per profile v3 §2.3
            timeline.append({"run": run_path.name, "error": str(exc)})
            continue
        counts = r.get("counts", {})
        n = len(r.get("questions", []))
        n_questions += n
        for cid, c in counts.items():
            totals[cid] = totals.get(cid, 0) + c.get("pass", 0)
        timeline.append({
            "run": run_path.name,
            "mtime_unix": int(run_path.stat().st_mtime),
            "n_questions": n,
            "counts": counts,
        })
    return {
        "schema_version": "v0",
        "generated_unix": int(time.time()),
        "n_runs": len(runs),
        "n_questions_total": n_questions,
        "totals_pass": totals,
        "timeline": timeline,
    }


def _atomic_write(path: Path, data: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        finally:
            raise


def main(argv: list[str]) -> int:
    result = aggregate()
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if "--write" in argv:
        ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime(result["generated_unix"]))
        out = EVAL_DIR / f"rubric-history-{ts}.json"
        _atomic_write(out, payload)
        print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
