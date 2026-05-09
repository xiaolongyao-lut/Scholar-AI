"""Morpheus round-2 probe: hit live uvicorn with harness-shaped payload and
capture full response body. Helps diagnose why run-20260425-055111 returned
4x500 with no visible stderr traceback."""
import json
import sys
import urllib.request
import urllib.error

SOURCE = r"C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\output"
QUERIES = [
    "激光熔池流动行为影响，匙孔如何控制？",
    "这篇文献主要研究了什么？",
    "文献库里关于焊缝结晶的控制有哪些相关研究？",
    "某种焊接工艺相关研究有哪些，写综述的材料？",
]


def probe(q: str) -> dict:
    payload = json.dumps({
        "query": q,
        "session_id": "morpheus-probe-r2",
        "tier": "balanced",
        "source_paths": [SOURCE],
    }).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:8767/api/chat",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    out = {"query": q}
    try:
        r = urllib.request.urlopen(req, timeout=180)
        out["status"] = r.status
        out["body"] = r.read(5000).decode("utf-8", errors="replace")[:3000]
    except urllib.error.HTTPError as e:
        out["status"] = e.code
        out["body"] = e.read(5000).decode("utf-8", errors="replace")[:3000]
    except Exception as e:
        out["status"] = None
        out["err"] = f"{type(e).__name__}: {str(e)[:300]}"
    return out


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    results = []
    for q in QUERIES[:n]:
        results.append(probe(q))
    print(json.dumps(results, ensure_ascii=False, indent=2))
