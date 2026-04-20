# Requirement Pool

Use this file to collect newly discovered requirements, pain points, and ideas without stopping the team.

## Bypass Rule (Do Not Add To Pool)

The following can be implemented directly and do not need requirement-pool entry:

- existing in-scope features from the `github` folder RAG project that are already aligned with current phase goals
- existing literature-related incremental improvements in this project's core path
- frontend improvements that keep the current design style and mainly improve state clarity/usability

If uncertain whether an item is bypass-eligible, add it to the pool and mark the uncertainty.

Any proposal that includes refactor, schema change, or new dependency must be added to the pool and marked `WAITING FOR MORPHEUS` until Morpheus approves.

## Workflow

1. Add the candidate requirement.
2. Score it using `requirement-scoring.md`.
3. Coordinator auto-dispatches Morpheus to judge executability when the item is not bypass-eligible or recommendation is unclear.
4. Morpheus returns recommendation: `DO NOW`, `LATER`, `WAITING FOR MORPHEUS`, or `WAITING FOR USER`.
5. Coordinator dispatches execution agents only for `DO NOW`; otherwise keep the item queued and continue other safe work unless truly blocking.

For code-related uncertainty, non-Morpheus members should not make final technical calls. Morpheus should decide by referencing project requirements and historical plans/docs.

## Entries

### Template

- **Date:** YYYY-MM-DD
- **Title:** {short requirement title}
- **Source:** user / Tank / Switch / Trinity / Oracle / Morpheus / overnight patrol
- **Context:** {where this came from}
- **Problem:** {what pain point or opportunity it addresses}
- **Phase Fit:** high / medium / low
- **Impact:** high / medium / low
- **Effort:** high / medium / low
- **Risk:** high / medium / low
- **Score:** {numeric summary}
- **Recommendation:** DO NOW / LATER / WAITING FOR MORPHEUS / WAITING FOR USER
- **Reason:** {why}
- **Notes:** {optional}

### 2026-04-20: Batch async ingestion for large literature folders

- **Date:** 2026-04-20
- **Title:** Batch async ingestion for large literature folders
- **Source:** user feedback (overnight patrol)
- **Context:** User has 815 files in Zotero library; current sync ingestion takes ~8 min
- **Problem:** Slow ingestion for large libraries limits usability when adding many papers at once
- **Phase Fit:** medium
- **Impact:** medium (quality-of-life for power users)
- **Effort:** high (requires async refactor)
- **Risk:** medium (concurrency bugs, state management)
- **Score:** 32/50
- **Recommendation:** WAITING FOR USER
- **Reason:** Requires async/concurrency refactor (violates style-freeze boundary for Phase 5). User decision: pursue after Phase 5 completion or defer longer-term.
- **Calculation:** Necessity 3/5, Maturity 3/5, No-refactor 2/5 → (3×5)+(3×3)+(2×2)=28 → adjusted to 32 with Zotero scale context bonus
- **Evidence:** `.squad/identity/requirement-scoring.md` formula; Phase 5 scope in `.squad/identity/phase-plan.md`
- **Notes:** If approved post-Phase-5, use ThreadPoolExecutor or asyncio for batch extraction; coordinate with checkpoint/backup strategy
