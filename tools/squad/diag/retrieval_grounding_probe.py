"""
Retrieval grounding probe — Morpheus round 3 diagnostic.

Goal: validate (or refute) the hypothesis that chat_router._extract_query_keywords
produces unsegmented CJK phrase-tokens that fail to substring-match anything in
output/ JSONs, causing all canonical queries to punt.

This script does NOT modify app code. It only:
  1. Imports _extract_query_keywords from my-project/src/routers/chat_router.py
  2. For each of the 4 canonical goal-drift §2 queries, prints the tokens it produces.
  3. Produces a Route-A candidate token list (char-bigram fallback for CJK tokens > 4 chars).
  4. Calls extract_literature_context(output/, keywords=...) under both schemes and
     reports chunk counts.

Exit 0 always — this is diagnostic. Run with:
    python tools/squad/diag/retrieval_grounding_probe.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_APP_SRC = _REPO_ROOT / "my-project" / "src"
sys.path.insert(0, str(_APP_SRC))

# Mirror chat_router._extract_query_keywords verbatim (as of 2026-04-25).
# Copied here to keep the probe free of LLM-gateway import side-effects.
_QUERY_KEYWORD_RE = re.compile(r"[\w一-鿿]+", re.UNICODE)


def _extract_query_keywords(query: str) -> list[str]:
    seen: set[str] = set()
    keywords: list[str] = []
    for token in _QUERY_KEYWORD_RE.findall(query):
        normalized = token.strip().casefold()
        if not normalized:
            continue
        if token.isascii() and len(normalized) < 2:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        keywords.append(token.strip())
    return keywords


# extraction_pipeline also has heavy transitive deps via keyword_filter; import lazily.
from extraction_pipeline import extract_literature_context  # type: ignore  # noqa: E402


CANONICAL_QUERIES = [
    "激光熔池流动行为影响，匙孔如何控制？",
    "这篇文献主要研究了什么？",
    "文献库里关于焊缝结晶的控制有哪些相关研究？",
    "某种焊接工艺相关研究有哪些，写综述的材料？",
]

OUTPUT_DIR = _REPO_ROOT / "output"


def is_cjk(ch: str) -> bool:
    return "一" <= ch <= "鿿"


def route_a_bigrams(tokens: list[str], min_phrase_len: int = 4) -> list[str]:
    """Char-bigram fallback for CJK tokens longer than min_phrase_len.

    For a token like '激光熔池流动行为影响' (10 CJK chars), produce bigrams
    ['激光','光熔','熔池', ... '影响']. For short CJK tokens or ASCII tokens,
    keep as-is.
    """
    seen: set[str] = set()
    out: list[str] = []
    for tok in tokens:
        cjk_run = all(is_cjk(c) for c in tok)
        if cjk_run and len(tok) > min_phrase_len:
            for i in range(len(tok) - 1):
                bg = tok[i : i + 2]
                if bg not in seen:
                    seen.add(bg)
                    out.append(bg)
        else:
            if tok not in seen:
                seen.add(tok)
                out.append(tok)
    return out


def count_chunks(keywords: list[str]) -> int:
    items = extract_literature_context(str(OUTPUT_DIR), keywords=keywords or None)
    return len(items)


def main() -> None:
    report = {
        "repo_root": str(_REPO_ROOT),
        "output_dir": str(OUTPUT_DIR),
        "output_exists": OUTPUT_DIR.is_dir(),
        "cases": [],
    }

    for q in CANONICAL_QUERIES:
        baseline_tokens = _extract_query_keywords(q)
        route_a_tokens = route_a_bigrams(baseline_tokens)

        baseline_chunks = count_chunks(baseline_tokens)
        route_a_chunks = count_chunks(route_a_tokens)

        case = {
            "query": q,
            "baseline_tokens": baseline_tokens,
            "baseline_chunks": baseline_chunks,
            "route_a_token_count": len(route_a_tokens),
            "route_a_tokens_sample": route_a_tokens[:10],
            "route_a_chunks": route_a_chunks,
            "verdict": (
                "route-a-improves"
                if route_a_chunks > baseline_chunks
                else ("both-zero" if route_a_chunks == 0 else "no-change")
            ),
        }
        report["cases"].append(case)

    # Force ASCII-safe output so Windows GBK stdout does not mangle Chinese.
    # Keep a UTF-8 copy next to the script for humans.
    text = json.dumps(report, ensure_ascii=False, indent=2)
    (Path(__file__).parent / "probe-out.json").write_text(text, encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
