"""Exec _extract_query_keywords from the live chat_router.py (no imports)."""
from __future__ import annotations
import json, re, sys
from pathlib import Path

_APP_SRC = Path(__file__).resolve().parents[3] / "my-project" / "src"
src = (_APP_SRC / "routers" / "chat_router.py").read_text(encoding="utf-8")

def grab(pattern: str) -> str:
    m = re.search(pattern, src, re.M)
    if not m:
        print(json.dumps({"error": f"missing pattern: {pattern}"})); sys.exit(2)
    return m.group(0)

body = grab(r"^_QUERY_KEYWORD_RE\s*=.*$")
cjk = grab(r"^_CJK_CHAR_RE\s*=.*$")
thr = grab(r"^_CJK_BIGRAM_THRESHOLD\s*=.*$")
# stopword set spans multiple lines
sw_match = re.search(r"^_CJK_STOPWORD_BIGRAMS\s*=\s*frozenset\(\{.*?\}\)", src, re.M | re.S)
func = re.search(r"^def _extract_query_keywords.*?(?=\n\ndef |\Z)", src, re.M | re.S)
if not func:
    print(json.dumps({"error": "no function body"})); sys.exit(2)

ns: dict = {"re": re}
exec(body, ns); exec(cjk, ns); exec(thr, ns)
if sw_match: exec(sw_match.group(0), ns)
else: ns["_CJK_STOPWORD_BIGRAMS"] = frozenset()
exec(func.group(0), ns)

queries = [
    "激光熔池流动行为影响，匙孔如何控制？",
    "这篇文献主要研究了什么？",
    "文献库里关于焊缝结晶的控制有哪些相关研究？",
    "某种焊接工艺相关研究有哪些，写综述的材料？",
]
print(json.dumps({
    "threshold": ns.get("_CJK_BIGRAM_THRESHOLD"),
    "cases": [{"query": q, "tokens": ns["_extract_query_keywords"](q)} for q in queries],
}, ensure_ascii=False, indent=2))
