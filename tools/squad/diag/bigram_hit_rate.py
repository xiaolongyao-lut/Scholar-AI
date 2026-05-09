"""Does Route A actually hit output/*.json? Direct substring scan, no pipeline.

For each canonical query, counts how many output/*.json files contain at least
one of the baseline tokens vs at least one of the Route-A bigrams.
"""
from __future__ import annotations
import json, re, unicodedata
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_OUTPUT = _REPO_ROOT / "output"
_RESULT = _REPO_ROOT / "tools" / "squad" / "diag" / "bigram-hitrate.json"

_QUERY_KEYWORD_RE = re.compile(r"[\w一-鿿]+", re.UNICODE)

CANONICAL = [
    "激光熔池流动行为影响，匙孔如何控制？",
    "这篇文献主要研究了什么？",
    "文献库里关于焊缝结晶的控制有哪些相关研究？",
    "某种焊接工艺相关研究有哪些，写综述的材料？",
]

def _tokens(q: str) -> list[str]:
    out, seen = [], set()
    for t in _QUERY_KEYWORD_RE.findall(q):
        n = t.strip().casefold()
        if not n or n in seen: continue
        if t.isascii() and len(n) < 2: continue
        seen.add(n); out.append(t.strip())
    return out

def is_cjk(c: str) -> bool: return "一" <= c <= "鿿"

def route_a(toks: list[str], min_len: int = 4) -> list[str]:
    seen, out = set(), []
    for t in toks:
        if all(is_cjk(c) for c in t) and len(t) > min_len:
            for i in range(len(t)-1):
                bg = t[i:i+2]
                if bg not in seen: seen.add(bg); out.append(bg)
        elif t not in seen:
            seen.add(t); out.append(t)
    return out

def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold()

# Pre-load all json files (normalized text), capped for speed.
files = sorted([p for p in _OUTPUT.glob("*.json") if p.is_file()])
# Limit: text under 5MB to avoid giant metrics files.
corpus = []
for p in files:
    try:
        if p.stat().st_size > 5_000_000: continue
        corpus.append((p.name, _norm(p.read_text(encoding="utf-8", errors="ignore"))))
    except Exception:
        continue

def hits(keywords: list[str]) -> dict:
    if not keywords: return {"hits": 0, "sample": []}
    norm_keys = [_norm(k) for k in keywords if k]
    hit_files = []
    for name, text in corpus:
        for k in norm_keys:
            if k and k in text:
                hit_files.append(name)
                break
    return {"hits": len(hit_files), "sample": hit_files[:5]}

report = {"output_dir": str(_OUTPUT), "files_scanned": len(corpus), "cases": []}
for q in CANONICAL:
    base = _tokens(q)
    ra = route_a(base)
    report["cases"].append({
        "query": q,
        "baseline_tokens": base,
        "baseline_hits": hits(base),
        "route_a_tokens": ra,
        "route_a_hits": hits(ra),
    })

_RESULT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"wrote {_RESULT}")
