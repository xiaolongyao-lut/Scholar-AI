"""Minimal sub-probe: tokenizer + bigram fallback. Writes to file.

Re-implements the exact regex from chat_router.py:19 to avoid the litellm
import chain. Any divergence from chat_router._extract_query_keywords would
be a bug in this probe, not the app.
"""
from __future__ import annotations
import json, re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Mirror of chat_router.py:19 and chat_router.py:358-371 (verified 2026-04-25).
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


CANONICAL = [
    "激光熔池流动行为影响，匙孔如何控制？",
    "这篇文献主要研究了什么？",
    "文献库里关于焊缝结晶的控制有哪些相关研究？",
    "某种焊接工艺相关研究有哪些，写综述的材料？",
]


def is_cjk(ch: str) -> bool:
    return "一" <= ch <= "鿿"


def route_a(tokens: list[str], min_len: int = 4) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if all(is_cjk(c) for c in t) and len(t) > min_len:
            for i in range(len(t) - 1):
                bg = t[i : i + 2]
                if bg not in seen:
                    seen.add(bg); out.append(bg)
        elif t not in seen:
            seen.add(t); out.append(t)
    return out


rows = []
for q in CANONICAL:
    base = _extract_query_keywords(q)
    rows.append({"query": q, "baseline": base, "route_a": route_a(base)})

out_path = _REPO_ROOT / "tools" / "squad" / "diag" / "tokens-result.json"
out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"wrote {out_path}")
