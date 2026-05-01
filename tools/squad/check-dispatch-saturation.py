#!/usr/bin/env python3
"""check-dispatch-saturation — refuse-to-dispatch predicate over queued-age data.

Reads the newest .squad/diagnostics/queued-age-*.json (produced by
queued-age-report.py) and emits a structured marker if any agent's queued-task
count exceeds --per-agent-cap, or if global queue depth + zero-lease combined
indicate the lease machinery is dead.

Spec anchor: requirement-pool 2026-04-25T15:15:00Z dispatch-backpressure
invariant. Goal-drift §4 line 88 (no silent failures), extended to dispatch
side: silent enqueue onto a saturated unleased lane IS a silent failure.

Pure stdlib. Read-only. No mutation. No subprocess. No network.

Exit codes:
  0  no saturation; safe to dispatch
  2  per-agent saturation (some agent exceeds --per-agent-cap)
  3  global lease-machinery-dead (total_queued >= --global-floor AND
       unleased_count == total_queued)
  4  no diagnostic available (run queued-age-report.py first)

Usage:
  py -3 tools/squad/check-dispatch-saturation.py [--per-agent-cap 20]
                                                 [--global-floor 200]
                                                 [--agent NAME]
                                                 [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DIAG_DIR = REPO_ROOT / ".squad" / "diagnostics"


def newest_diagnostic() -> Path | None:
    if not DIAG_DIR.is_dir():
        return None
    candidates = sorted(
        DIAG_DIR.glob("queued-age-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def evaluate(payload: dict, per_agent_cap: int, global_floor: int,
             only_agent: str | None) -> tuple[int, dict]:
    by_assigned = payload.get("by_assigned", {}) or {}
    total = int(payload.get("total_queued", 0) or 0)
    unleased = int(payload.get("unleased_count", 0) or 0)

    # Global lease-machinery-dead check is independent of any single agent.
    global_dead = total >= global_floor and unleased == total and total > 0

    # Per-agent saturation. If --agent is given, only that one is examined.
    if only_agent is not None:
        items = [(only_agent, int(by_assigned.get(only_agent, 0)))]
    else:
        items = [(k, int(v)) for k, v in by_assigned.items()]
    saturated = [(name, n) for name, n in items if n > per_agent_cap]

    verdict = {
        "captured_at": payload.get("captured_at"),
        "total_queued": total,
        "unleased_count": unleased,
        "global_dead": global_dead,
        "per_agent_cap": per_agent_cap,
        "global_floor": global_floor,
        "saturated_agents": [
            {"agent": name, "queued": n} for name, n in
            sorted(saturated, key=lambda kv: -kv[1])
        ],
    }

    if global_dead:
        return 3, verdict
    if saturated:
        return 2, verdict
    return 0, verdict


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-agent-cap", type=int, default=20,
                    help="refuse dispatch if any agent has > this many queued (default 20)")
    ap.add_argument("--global-floor", type=int, default=200,
                    help="global lease-dead threshold for total_queued (default 200)")
    ap.add_argument("--agent", type=str, default=None,
                    help="if given, only check this single agent's saturation")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON verdict to stdout instead of one-line marker")
    args = ap.parse_args()

    diag = newest_diagnostic()
    if diag is None:
        msg = (f"DISPATCH-SATURATION no_diagnostic dir={DIAG_DIR} "
               f"(run queued-age-report.py first)")
        if args.json:
            print(json.dumps({"status": "no_diagnostic", "dir": str(DIAG_DIR)}))
        else:
            print(msg)
        return 4

    payload = json.loads(diag.read_text(encoding="utf-8"))
    code, verdict = evaluate(payload, args.per_agent_cap, args.global_floor,
                             args.agent)
    verdict["diagnostic"] = diag.name

    if args.json:
        print(json.dumps(verdict, ensure_ascii=False))
    else:
        if code == 3:
            print(
                f"DISPATCH-SATURATION lease_machinery_dead "
                f"total={verdict['total_queued']} "
                f"unleased={verdict['unleased_count']} "
                f"diag={diag.name}"
            )
        elif code == 2:
            top = verdict["saturated_agents"][0]
            print(
                f"DISPATCH-SATURATION per_agent agent={top['agent']} "
                f"queued={top['queued']} cap={args.per_agent_cap} "
                f"saturated_n={len(verdict['saturated_agents'])} "
                f"diag={diag.name}"
            )
        else:
            print(
                f"DISPATCH-SATURATION ok total={verdict['total_queued']} "
                f"unleased={verdict['unleased_count']} "
                f"diag={diag.name}"
            )
    return code


if __name__ == "__main__":
    sys.exit(main())
