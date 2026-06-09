"""Discussion citation marker parser.

Per the discussion evidence trace contract,
(marker syntax `[E:E<n>]`) and D-DET-4 (silently drop unknown ids).

Best-effort parser: failure is silent. Never raises. Caller treats an empty
return as "no citations parsed" and the orchestrator stores it on
`DiscussionAgentTrace.cited_evidence_ids` directly.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

CITATION_PATTERN = re.compile(r"\[E:(?P<id>E\d+)\]")


def parse_cited_evidence_ids(
    answer: str,
    valid_ids: Sequence[str],
) -> list[str]:
    """Extract citation marker ids from an agent answer.

    Walks `[E:E<n>]` matches in `answer` (case-sensitive — see D-DET-1),
    keeps only those present in `valid_ids`, deduplicates while preserving
    the order of first occurrence. Unknown ids are dropped silently
    (D-DET-4) so a hallucinated `[E:E99]` does not poison the trace.

    Args:
        answer: Raw agent answer text. May be empty.
        valid_ids: Whitelist of evidence ids registered for this run
            (typically `pack.evidence_ids`).

    Returns:
        Ordered, deduplicated list of cited ids. Empty list when no markers
        match, when `valid_ids` is empty, or when the answer is empty.
    """
    if not answer or not valid_ids:
        return []
    valid_set = set(valid_ids)
    seen: set[str] = set()
    out: list[str] = []
    for match in CITATION_PATTERN.finditer(answer):
        eid = match.group("id")
        if eid in valid_set and eid not in seen:
            seen.add(eid)
            out.append(eid)
    return out


def build_evidence_ids(snippet_count: int) -> list[str]:
    """Generate the canonical per-run evidence id sequence.

    Per D-DET-2 ids are `E1`, `E2`, ... matching index in
    `pack.snippets` (1-indexed for human readability in prompts).

    Args:
        snippet_count: Number of snippets in the evidence pack.

    Returns:
        List of length `snippet_count` with the canonical ids.
    """
    if snippet_count <= 0:
        return []
    return [f"E{i}" for i in range(1, snippet_count + 1)]


CITATION_CONTRACT_SUFFIX = (
    "\n\nCitation format:\n"
    "When a sentence is supported by an evidence snippet, append the marker "
    "[E:E<n>] immediately after that sentence, where E<n> is the id shown "
    "next to the snippet (E1, E2, …). Use only ids from the provided "
    "evidence list. Do not invent ids. Do not cite when no evidence supports "
    "the claim."
)


__all__ = [
    "CITATION_CONTRACT_SUFFIX",
    "CITATION_PATTERN",
    "build_evidence_ids",
    "parse_cited_evidence_ids",
]
