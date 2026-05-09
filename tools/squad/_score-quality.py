"""Pool entry 4301-4330 v0 sidecar: stdin {response_text, citations} → stdout {quality_score, quality_pass}.

Bridges the round-4 quality_heuristic.score() into run-rag-once.ps1 per-question post-200 hook.
Pure stdlib. No LLM. Fail-closed: any parse/import error returns {quality_score:null, quality_pass:false} on stdout
and exit 1 to stderr-log the cause without crashing the harness.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "my-project"))


def _fail_closed(msg: str) -> int:
    sys.stdout.write(json.dumps({"quality_score": None, "quality_pass": False, "error": msg}))
    return 1


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        return _fail_closed(f"stdin not valid JSON: {e}")

    response_text = payload.get("response_text")
    citations = payload.get("citations") or []
    if not isinstance(response_text, str) or not response_text.strip():
        sys.stdout.write(json.dumps({"quality_score": None, "quality_pass": False}))
        return 0
    if not isinstance(citations, list):
        return _fail_closed("citations field is not a list")

    try:
        from src.quality_heuristic import score
    except ImportError as e:
        return _fail_closed(f"cannot import quality_heuristic: {e}")

    try:
        result = score(response_text, citations, gold_text=None)
    except Exception as e:  # noqa: BLE001 — fail-closed bridge
        return _fail_closed(f"score() raised: {type(e).__name__}: {e}")

    sys.stdout.write(json.dumps({
        "quality_score": asdict(result),
        "quality_pass": bool(result.overall_pass),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
