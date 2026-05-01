"""Verify ChatResponse schema exposes citations + the harness consumes them.

Round-10 finding (`.squad/state/round-10-pool-block.md` 2026-04-26T05:35Z):
goal-drift §3.3 L83 (wenxianku diff report) and §4 L93 (citation_auditor)
both require citation-keyed traceability from the eval harness back to source
documents. Current state:

  - `my-project/src/routers/chat_router.py:113-120` defines `ChatResponse`
    with fields {response, session_id, context_chunks_used, tokens_used,
    tier_used, context_metadata, actual_sampling_params} — NO `citations`.
  - `tools/squad/run-rag-once.ps1:158-184` populates harness `citations` ONLY
    if `$parsed.citations` exists; against current API it never does, so
    every eval reports `citation_count=0` regardless of what was retrieved.

Even if LLM credentials land (HARD-STOP `6908f3cc`), the harness has no
machine path from response → wenxianku qrels for the L83 diff report.

This checker is a static verifier:
  - greps `class ChatResponse` body for a `citations` field
  - greps `run-rag-once.ps1` for `parsed.citations` consumption
  - emits one machine-readable summary line; non-zero exit if gap persists

Pure stdlib. Read-only. Distinct from check-eval-* family (operates on schema
SOURCE not eval JSON) and from resolve-qrels-to-doc-keys.py (different layer).

Usage:
    py tools/squad/check-chat-response-citations.py

Output line format (single line, grep-able):
    CHAT-CITATIONS <status> schema=<has|missing> harness=<reads|ignores> note=<short>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROUTER = REPO / "my-project" / "src" / "routers" / "chat_router.py"
HARNESS = REPO / "tools" / "squad" / "run-rag-once.ps1"


def schema_has_citations(text: str) -> bool:
    """Return True iff `class ChatResponse` body declares a `citations` field."""
    m = re.search(r"class\s+ChatResponse\s*\([^)]*\)\s*:\s*\n(.+?)(?=\n\nclass|\Z)", text, re.DOTALL)
    if not m:
        return False
    body = m.group(1)
    # Match a line like `    citations: <type>...` (indented, before the empty-line break).
    return re.search(r"^\s+citations\s*:", body, re.MULTILINE) is not None


def harness_reads_citations(text: str) -> bool:
    """Return True iff harness has a parsed.citations consumption branch."""
    return "parsed.citations" in text or "$parsed.citations" in text


def main() -> int:
    if not ROUTER.is_file():
        print(f"CHAT-CITATIONS missing router={ROUTER}")
        return 3
    if not HARNESS.is_file():
        print(f"CHAT-CITATIONS missing harness={HARNESS}")
        return 3

    schema_has = schema_has_citations(ROUTER.read_text(encoding="utf-8"))
    harness_reads = harness_reads_citations(HARNESS.read_text(encoding="utf-8"))

    schema_tag = "has" if schema_has else "missing"
    harness_tag = "reads" if harness_reads else "ignores"

    if schema_has and harness_reads:
        status, note = "wired", "end-to-end-citation-path-present"
        rc = 0
    elif (not schema_has) and harness_reads:
        status, note = "gap-schema-only", "harness-reads-but-API-does-not-emit"
        rc = 5
    elif schema_has and (not harness_reads):
        status, note = "gap-harness-only", "API-emits-but-harness-discards"
        rc = 5
    else:
        status, note = "gap-both-ends", "neither-API-emits-nor-harness-reads"
        rc = 5

    print(
        f"CHAT-CITATIONS {status} schema={schema_tag} harness={harness_tag} note={note}"
    )
    return rc


if __name__ == "__main__":
    sys.exit(main())
