"""Materialize the canonical wenxianku qrels v0 from markdown to TREC TSV.

The doc `.squad/audits/canonical-qrels-v0-2026-04-25-0934.md` (round-11
2026-04-25 09:34, parent of GC'd qrels-harness tasks ccf57765 / a156f371 /
53dc6484) embeds a TREC-format aggregation block in a fenced code section.
This tool extracts that block to a sibling .tsv so any future scorer harness
can consume it directly without re-parsing markdown.

Goal-drift anchors:
  §3.2 line 73 (multi-turn) — Q2 explicitly marked test-skip in v0
  §3.3 line 83 (wenxianku diff report) — qrels is the answer-key foundation
Profile/benchmark anchor: 用户画像 v4 §"DoD 是可机器核验的命令" — TSV is the
machine-verifiable form; markdown table is human-readable form.

Pure stdlib. Zero pip dep. Read-only on `.squad/audits/` source; writes one
file via .tmp + os.replace (CLAUDE.md §4.7 atomic-write). Distinct from
audit-wenxianku-filename-hazards.py (filename hazards) and from
check-eval-* family (eval JSON, not qrels).

Usage:
    py tools/squad/materialize-qrels-v0.py [--check]

  default: write `.squad/audits/canonical-qrels-v0.tsv` and emit summary line
  --check: parse and verify only, do not write (exit 0 if parseable)

Output line format (single line, grep-able):
    QRELS-V0 <status> source=<src> dest=<dest> queries=<N> rows=<N>
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / ".squad" / "audits" / "canonical-qrels-v0-2026-04-25-0934.md"
DEST = REPO / ".squad" / "audits" / "canonical-qrels-v0.tsv"

# Match `<query-id> 0 <doc-id> <grade>` lines inside a fenced code block.
TREC_LINE = re.compile(r"^(Q\d+)\s+0\s+(\S+)\s+(\d+)\s*$")


def extract_trec_block(text: str) -> list[tuple[str, str, str, int]]:
    """Find the first fenced ```...``` block whose lines parse as TREC qrels."""
    blocks = re.findall(r"```\s*\n(.*?)```", text, re.DOTALL)
    for block in blocks:
        rows: list[tuple[str, str, str, int]] = []
        ok = True
        for line in block.splitlines():
            line = line.strip()
            if not line:
                continue
            m = TREC_LINE.match(line)
            if not m:
                ok = False
                break
            rows.append((m.group(1), "0", m.group(2), int(m.group(3))))
        if ok and rows:
            return rows
    return []


def atomic_write(dest: Path, content: str) -> None:
    """`.tmp` + `os.replace` per CLAUDE.md §4.7."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp, dest)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true", help="parse-only, no write")
    args = p.parse_args()

    if not SOURCE.is_file():
        print(f"QRELS-V0 missing source={SOURCE}")
        return 3

    text = SOURCE.read_text(encoding="utf-8")
    rows = extract_trec_block(text)
    if not rows:
        print(f"QRELS-V0 unparseable source={SOURCE.name} block_not_found_or_invalid")
        return 4

    queries = sorted({r[0] for r in rows})

    if args.check:
        print(
            f"QRELS-V0 parseable source={SOURCE.name} "
            f"queries={len(queries)} rows={len(rows)} qids={','.join(queries)}"
        )
        return 0

    body = "\n".join(f"{qid}\t{zero}\t{doc}\t{grade}" for (qid, zero, doc, grade) in rows) + "\n"
    atomic_write(DEST, body)
    print(
        f"QRELS-V0 materialized source={SOURCE.name} dest={DEST.name} "
        f"queries={len(queries)} rows={len(rows)} qids={','.join(queries)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
