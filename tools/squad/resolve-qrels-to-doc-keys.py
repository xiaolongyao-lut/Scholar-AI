"""Resolve canonical-qrels-v0.tsv doc-ids to doc_store mat_<hash> keys.

Round-8 finding (`.squad/state/round-8-pool-block.md` 2026-04-26T04:43:18Z)
surfaced a three-way mismatch: round-7 qrels TSV doc-ids are filename-style
(e.g. `IJHMT2025-华中科技大学-激光焊接过程中三维`) while the wenxianku
benchmark sits in `output/doc_store/proj_9dbd42a14fb2.json` keyed by
`mat_<hash>` with `title` field equal to original PDF filename (some Chinese
titles arrive mojibake-encoded GBK→UTF-8). No scorer can run end-to-end
without a bridge between these two ID spaces.

This tool reads:
  - `.squad/audits/canonical-qrels-v0.tsv`              (round-7 output)
  - `output/doc_store/proj_9dbd42a14fb2.json`           (wenxianku index)

Emits:
  - `.squad/audits/canonical-qrels-v0-resolved.tsv`     (5 cols: qid 0 mat_hash grade orig_doc_id)
  - one summary line on stdout (grep-able)

Resolution rule: substring match between the qrels doc-id (or its longest
ASCII prefix when the id contains Chinese) and the doc_store entry's `title`
or `source_relative_path`. Mojibake titles are handled by attempting both
direct match and a GBK-decode-attempt of the bytes-form of the title.

Pure stdlib. Read-only on inputs; writes one file via .tmp + os.replace
(CLAUDE.md §4.7 atomic-write). Distinct from materialize-qrels-v0.py
(markdown→TSV materializer) and from audit-wenxianku-filename-hazards.py
(filename-class hazards).

Usage:
    py tools/squad/resolve-qrels-to-doc-keys.py [--check]

  default: write resolved TSV + emit summary line
  --check: parse + resolve only, no write (exit 0 if all rows resolve)

Output line format (single line, grep-able):
    QRELS-RESOLVE <status> qrels_rows=<N> resolved=<N> unresolved=<N> docs=<N>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
QRELS_TSV = REPO / ".squad" / "audits" / "canonical-qrels-v0.tsv"
DOC_STORE = REPO / "output" / "doc_store" / "proj_9dbd42a14fb2.json"
OUT_TSV = REPO / ".squad" / "audits" / "canonical-qrels-v0-resolved.tsv"


def load_qrels(p: Path) -> list[tuple[str, str, str, str]]:
    """Return list of (qid, '0', doc_id, grade) from TREC TSV."""
    out: list[tuple[str, str, str, str]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        out.append((parts[0], parts[1], parts[2], parts[3]))
    return out


def load_doc_index(p: Path) -> dict[str, dict]:
    """Load doc_store JSON. Keys are mat_<hash>, values are records."""
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def candidate_keys(title: str, src_path: str) -> list[str]:
    """Build matchable strings from a doc_store record."""
    keys: list[str] = []
    if title:
        keys.append(title)
        # strip trailing .pdf and try again
        if title.lower().endswith(".pdf"):
            keys.append(title[:-4])
    if src_path:
        keys.append(src_path)
    # Mojibake recovery attempt: title may be GBK bytes mis-decoded as latin-1/utf-8
    # The pattern in proj_9dbd42a14fb2 is text encoded as GBK then surrogate-escaped.
    if title:
        try:
            recoded = title.encode("latin-1", errors="ignore").decode("gbk", errors="ignore")
            if recoded and recoded != title:
                keys.append(recoded)
        except Exception:
            pass
    return keys


def resolve_one(qrels_doc_id: str, index: dict[str, dict]) -> str | None:
    """Return mat_<hash> key whose title/path best matches qrels_doc_id, else None."""
    # Take ASCII prefix as the strongest signal — that's the part of the
    # qrels-doc-id likely to match the original filename verbatim.
    ascii_prefix = ""
    for ch in qrels_doc_id:
        if ord(ch) < 128:
            ascii_prefix += ch
        else:
            break
    ascii_prefix = ascii_prefix.rstrip("-_ ")

    needles = [qrels_doc_id]
    if ascii_prefix and ascii_prefix != qrels_doc_id:
        needles.append(ascii_prefix)

    for mat_key, rec in index.items():
        title = rec.get("title", "") or ""
        src = rec.get("source_relative_path", "") or ""
        cands = candidate_keys(title, src)
        cand_blob = "\n".join(cands).lower()
        for needle in needles:
            n = needle.lower().strip()
            if not n:
                continue
            if n in cand_blob:
                return mat_key
    return None


def atomic_write(dest: Path, content: str) -> None:
    """`.tmp` + `os.replace` per CLAUDE.md §4.7."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp, dest)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true", help="resolve-only, no write")
    args = p.parse_args()

    if not QRELS_TSV.is_file():
        print(f"QRELS-RESOLVE missing qrels={QRELS_TSV}")
        return 3
    if not DOC_STORE.is_file():
        print(f"QRELS-RESOLVE missing doc_store={DOC_STORE}")
        return 3

    qrels = load_qrels(QRELS_TSV)
    index = load_doc_index(DOC_STORE)

    rows_out: list[tuple[str, str, str, str, str]] = []  # qid, 0, mat_or_UNRESOLVED, grade, orig
    unresolved = 0
    for (qid, zero, doc_id, grade) in qrels:
        mat = resolve_one(doc_id, index)
        if mat is None:
            unresolved += 1
            rows_out.append((qid, zero, "UNRESOLVED", grade, doc_id))
        else:
            rows_out.append((qid, zero, mat, grade, doc_id))

    resolved = len(qrels) - unresolved
    status = "complete" if unresolved == 0 else ("partial" if resolved > 0 else "empty")

    if args.check:
        print(
            f"QRELS-RESOLVE {status} qrels_rows={len(qrels)} resolved={resolved} "
            f"unresolved={unresolved} docs={len(index)}"
        )
        return 0 if unresolved == 0 else 5

    body_lines = [f"{q}\t{z}\t{m}\t{g}\t{o}" for (q, z, m, g, o) in rows_out]
    body = "\n".join(body_lines) + "\n"
    atomic_write(OUT_TSV, body)
    print(
        f"QRELS-RESOLVE {status} qrels_rows={len(qrels)} resolved={resolved} "
        f"unresolved={unresolved} docs={len(index)} dest={OUT_TSV.name}"
    )
    return 0 if unresolved == 0 else 5


if __name__ == "__main__":
    sys.exit(main())
