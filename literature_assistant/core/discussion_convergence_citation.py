"""Discussion convergence by citation overlap (Sub-plan #7, helper-only slice).

Per `docs/plans/active/2026-05-16-discussion-citation-overlap-convergence-plan.md`
this module provides the calculation primitives for an opt-in, citation-
overlap based convergence signal. The orchestrator default auto-stop
(embedding similarity + LLM judge in `discussion_convergence.py`) is **NOT**
modified; that integration is a separate future slice that will surface a
`DiscussionRunConfig.convergence_strategy` enum field after dogfood data
exists.

Locked decisions consumed here (D-CITECONV-2 / D-CITECONV-3 / D-CITECONV-4 /
D-CITECONV-5 from the sub-plan):

- D-CITECONV-2: empty-vs-empty Jaccard returns 0.0 for convergence
  decisions (not the mathematical 1.0). A run where nobody cites evidence
  must NOT be considered converged via this signal; it falls through to
  the existing auto-stop path or runs to `max_turns`.
- D-CITECONV-3: threshold is **customizable per call**, never hard-coded
  into release behavior. Caller must pass it explicitly.
- D-CITECONV-4: caller is responsible for enforcing `min_turns` and the
  "at least two agents cited evidence in both compared turns" gate; this
  module exposes the raw similarity and a thin convenience wrapper.
- D-CITECONV-5: when no evidence pack exists for the run, every turn's
  cited set is empty, and `citation_overlap_converged` returns
  `(False, 0.0)` regardless of threshold. Behavior is identical to no-MCP
  / no-pack discussions.

Pure functions; no side effects; no LLM calls; deterministic.
"""

from __future__ import annotations

from collections.abc import Sequence

from models.discussion import DiscussionTurnTrace


def turn_cited_set(turn: DiscussionTurnTrace) -> frozenset[str]:
    """Union of cited evidence ids across all *successful* agents in a turn.

    Failed agent traces (success=False) contribute nothing. An agent with
    no `cited_evidence_ids` (or with an empty list) contributes nothing.
    Returns an immutable, hashable set so downstream code can cache or
    use as dict keys without copying.
    """
    out: set[str] = set()
    for trace in turn.agent_traces:
        if trace.success:
            cited = trace.cited_evidence_ids or ()
            out.update(cited)
    return frozenset(out)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity with the D-CITECONV-2 empty-set rule.

    Returns 0.0 when **either** set is empty (so empty runs do not falsely
    converge). When both sets are non-empty, returns the standard
    `|a ∩ b| / |a ∪ b|`.

    Range: 0.0 .. 1.0. Float precision; not normalized for FP rounding
    because the result is consumed by `>= threshold` comparisons that
    tolerate single-ULP differences.
    """
    if not a or not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0  # belt-and-suspenders; unreachable given the guards above
    return len(a & b) / len(union)


def citation_overlap_converged(
    turns: Sequence[DiscussionTurnTrace],
    *,
    threshold: float,
    min_turns: int = 2,
) -> tuple[bool, float]:
    """Is the most recent turn citation-converged with the previous one?

    Returns `(done, similarity)`:

    - `done=True` when `len(turns) >= min_turns` AND `len(turns) >= 2` AND
      Jaccard(turns[-1].cited, turns[-2].cited) >= threshold AND the
      compared sets are both non-empty (D-CITECONV-2 / D-CITECONV-4).
    - `done=False` otherwise. The returned similarity always reflects the
      most recent comparable pair (or `0.0` when there is nothing to
      compare).

    Args:
        turns: chronologically ordered list of `DiscussionTurnTrace`.
        threshold: caller-supplied stop threshold. Must be 0.0 .. 1.0.
            Caller is responsible for the calibration policy; this module
            does not impose a default (per D-CITECONV-3).
        min_turns: minimum number of accumulated turns before a stop
            decision is allowed (mirrors `DiscussionRunConfig.min_turns`).
            Default 2 because Jaccard between fewer than 2 turns is
            undefined.

    Caller is responsible for:
        - Honoring `DiscussionRunConfig.min_turns`.
        - Skipping the citation path when `evidence_pack` is absent
          (D-CITECONV-5) — though passing empty turns through this
          function is also safe and yields `(False, 0.0)`.
        - Threshold calibration once dogfood data is available.
    """
    if threshold < 0.0 or threshold > 1.0:
        raise ValueError(f"threshold must be in [0.0, 1.0], got {threshold!r}")
    if min_turns < 2:
        raise ValueError(f"min_turns must be >= 2 for pairwise comparison, got {min_turns!r}")
    if len(turns) < max(2, min_turns):
        return False, 0.0
    last = turn_cited_set(turns[-1])
    prev = turn_cited_set(turns[-2])
    sim = jaccard(last, prev)
    if not last or not prev:
        # Either turn lacked any successful citation; refuse to converge.
        return False, sim
    return sim >= threshold, sim


__all__ = [
    "citation_overlap_converged",
    "jaccard",
    "turn_cited_set",
]
