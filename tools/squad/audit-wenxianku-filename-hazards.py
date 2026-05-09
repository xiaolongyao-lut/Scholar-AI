"""Audit wenxianku/文献推荐版/ filenames for 3 known hazard classes that will
break the wenxianku-gold-set-scorer (pool task 43/50, UUID ccf57765) when it
ingests these PDFs as the {canonical_question -> gold_pdf} mapping target.

Hazards checked (read-only, pure stdlib):
  H1  fullwidth-pipe (U+FF5C '｜') in filename
        -> survives UTF-8 round-trip but breaks any downstream splitter that
           treats '|' as a delimiter; visual confusable with halfwidth pipe.
  H2  trailing-dots before extension ('foo....pdf')
        -> Windows path API silently strips trailing dots from the resolved
           path; Path('foo....pdf').exists() can return False even when the
           file is on disk literally as 'foo....pdf'. Same hazard class as
           pool line 358 cp936/surrogate bug — silent filesystem mismatch.
  H3  halfwidth ASCII 'I' (U+0049) used as visual delimiter
        -> Looks like '丨' or '|' but is a word character. Tokenizers that
           split on whitespace + punct will fuse 'IJHMT2025 I 华中科技大学'
           into 'IJHMT2025I华中科技大学' under aggressive normalization.

Output: writes .squad/audits/wenxianku-filename-hazards-<DATE>.md atomically
        (.tmp + os.replace) per CLAUDE.md §4.7. Exit 0 always — this is an
        observation tool, not a gate.

Re-run: `py -3 tools/squad/audit-wenxianku-filename-hazards.py`
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

WENXIANKU = Path("C:/Users/xiao/Desktop/wenxianku/文献推荐版")
AUDITS = Path(__file__).resolve().parents[2] / ".squad" / "audits"

FULLWIDTH_PIPE = "｜"  # ｜


def scan(pdf_dir: Path) -> list[dict]:
    rows = []
    if not pdf_dir.is_dir():
        return rows
    for entry in sorted(pdf_dir.iterdir()):
        if not entry.is_file():
            continue
        name = entry.name
        stem, ext = os.path.splitext(name)
        h1 = FULLWIDTH_PIPE in name
        h2 = stem.endswith(".") or stem.endswith("..") or stem.endswith("...")
        # H3: any run of non-CJK non-space chars wrapped in spaces with bare 'I'
        # Heuristic: tokens split on whitespace, look for single 'I' as a token.
        tokens = name.split()
        h3 = "I" in tokens
        rows.append(
            {
                "name": name,
                "h1_fullwidth_pipe": h1,
                "h2_trailing_dots": h2,
                "h3_bare_I_delimiter": h3,
                "exists_via_path": entry.exists(),  # control: did Path resolve OK?
            }
        )
    return rows


def render_report(rows: list[dict]) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# wenxianku 文献推荐版 filename-hazard audit",
        f"",
        f"Generated: {ts}",
        f"Source dir: `{WENXIANKU}`",
        f"File count: {len(rows)}",
        f"",
        f"## Per-file hazard matrix",
        f"",
        f"| # | filename | H1 ｜ | H2 trailing-dots | H3 bare-I | path.exists |",
        f"|---|----------|-------|------------------|-----------|-------------|",
    ]
    h1_n = h2_n = h3_n = exists_n = 0
    for i, r in enumerate(rows, 1):
        h1 = "YES" if r["h1_fullwidth_pipe"] else "no"
        h2 = "YES" if r["h2_trailing_dots"] else "no"
        h3 = "YES" if r["h3_bare_I_delimiter"] else "no"
        ex = "YES" if r["exists_via_path"] else "no"
        h1_n += r["h1_fullwidth_pipe"]
        h2_n += r["h2_trailing_dots"]
        h3_n += r["h3_bare_I_delimiter"]
        exists_n += r["exists_via_path"]
        # truncate long names for table readability
        nm = r["name"] if len(r["name"]) <= 50 else r["name"][:47] + "..."
        lines.append(f"| {i} | `{nm}` | {h1} | {h2} | {h3} | {ex} |")
    lines += [
        f"",
        f"## Summary",
        f"",
        f"- H1 fullwidth-pipe `｜` count: **{h1_n}/{len(rows)}**",
        f"- H2 trailing-dots before .pdf: **{h2_n}/{len(rows)}**",
        f"- H3 bare-`I` delimiter token: **{h3_n}/{len(rows)}**",
        f"- Path.exists() control: **{exists_n}/{len(rows)}** (sanity check; "
        f"if < {len(rows)}, H2 silent-strip is biting)",
        f"",
        f"## Verdict",
        f"",
    ]
    if h1_n + h2_n + h3_n == 0:
        lines.append("All filenames clean. wenxianku-gold-set-scorer (43/50 "
                     "task ccf57765) can ingest these names without normalization.")
    else:
        lines.append(f"Hazards present. The 43/50 wenxianku-gold-set-scorer task "
                     f"body MUST be amended to specify a normalization step "
                     f"before {{canonical_question -> gold_pdf}} mapping is "
                     f"materialized. Recommended normalization:")
        lines.append("")
        lines.append("- H1 -> replace `\\uFF5C` with `_` or strip")
        lines.append("- H2 -> rstrip('.') on stem before extension recombination")
        lines.append("- H3 -> tokenizer must NOT treat ASCII `I` as a word char "
                     "when surrounded by whitespace and CJK")
    lines.append("")
    return "\n".join(lines)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def main() -> int:
    rows = scan(WENXIANKU)
    report = render_report(rows)
    date = datetime.now().strftime("%Y-%m-%d")
    out = AUDITS / f"wenxianku-filename-hazards-{date}.md"
    atomic_write(out, report)
    print(f"wrote {out}")
    print(f"files_scanned={len(rows)} "
          f"h1={sum(r['h1_fullwidth_pipe'] for r in rows)} "
          f"h2={sum(r['h2_trailing_dots'] for r in rows)} "
          f"h3={sum(r['h3_bare_I_delimiter'] for r in rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
