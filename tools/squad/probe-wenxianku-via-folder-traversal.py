"""Probe whether wenxianku stems are reachable via the runtime retrieval path.

Round-11 finding (`.squad/state/round-11-pool-block.md` 2026-04-26T06:06:21Z):
the eval harness `tools/squad/run-rag-once.ps1:166-167` hardcodes
`source_paths=@(<repo>/output)` and POSTs that to `/api/chat`. The chat router
then folder-traverses that root via `collect_folder_records()` with default
extensions `{.json, .jsonl, .csv, .txt}`. Because `output/doc_store/proj_9dbd42a14fb2.json`
sits under that root, the wenxianku records ARE pulled into the runtime
retrieval candidate set — even though no doc_store *key space* is reachable
through the API response.

This probe re-runs the data flow:
  1. invoke `collect_folder_records('output')`
  2. count total records
  3. assert each wenxianku stem (case-insensitive substring) is present in
     the serialized record set

Pure stdlib + project src import. Read-only. Distinct from
check-chat-response-citations.py (round-10, schema↔harness contract) and
from resolve-qrels-to-doc-keys.py (round-9, offline mat_hash bridge).

The probe's value is to give future rounds (and owner triage) a one-shot
verifier that the source_paths=output retrieval root still surfaces the
wenxianku candidate set; if a future ingestion refactor breaks this, the
probe goes red BEFORE goal-drift §3.3 L83 silently regresses.

Usage:
    py tools/squad/probe-wenxianku-via-folder-traversal.py

Output line format (single line, grep-able):
    WENXIANKU-PROBE <status> records=<N> stems_hit=<N>/<N> root=output
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "my-project" / "src"

# Same set of 10 unique stems used in round-8 and round-9 scans.
WENXIANKU_STEMS = [
    "1-s2.0-S0924013625003887",
    "1-s2.0-S152661252600277X",
    "eng-07-00129",
    "materials-19-01104",
    "olt2026文献",
    "s40436-026-00596-x",
    "s41467-025-60162-0",
    "IJHMT2025",
    "OLT2026",
    "Nature Communications",
]


def main() -> int:
    sys.path.insert(0, str(SRC))
    try:
        from folder_traversal import collect_folder_records
    except Exception as exc:
        print(f"WENXIANKU-PROBE import_failed err={exc!r}")
        return 3

    output_root = REPO / "output"
    if not output_root.is_dir():
        print(f"WENXIANKU-PROBE missing root={output_root}")
        return 3

    try:
        records = collect_folder_records(str(output_root))
    except Exception as exc:
        print(f"WENXIANKU-PROBE traverse_failed err={exc!r}")
        return 4

    blob = json.dumps(records, ensure_ascii=False).lower()
    hit = 0
    misses: list[str] = []
    for stem in WENXIANKU_STEMS:
        if stem.lower() in blob:
            hit += 1
        else:
            misses.append(stem)

    total = len(WENXIANKU_STEMS)
    if hit == total:
        status = "reachable"
        rc = 0
    elif hit > 0:
        status = "partial"
        rc = 5
    else:
        status = "unreachable"
        rc = 6

    extra = f" misses={','.join(misses)}" if misses else ""
    print(
        f"WENXIANKU-PROBE {status} records={len(records)} "
        f"stems_hit={hit}/{total} root=output{extra}"
    )
    return rc


if __name__ == "__main__":
    sys.exit(main())
