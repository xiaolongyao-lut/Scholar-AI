### 2026-04-21: Tier 0 Gate Decision — Per-Query Quality Persistence Before Any Paid Eval

**By:** Morpheus (Architect / QA Lead)
**Requested by:** 小龙 姚
**Status:** ✅ APPROVED — Tier 0 may proceed without user approval

---

## Decision

**YES — Tier 0 can proceed.** It does not cross any hard-stop boundary.

---

## Root-Cause Evidence (code audit)

The 1100/3269 U1A run wasted money because of a single architectural defect in `eval_retrieval_runtime.py`:

- **Lines 795-812:** `_eval_one()` computes full per-query quality metrics (recall@1/3/5/10, mrr, latency, rerank timing) into a `result` dict.
- **Lines 813-827:** The progress reporter receives this `result` but writes **only counters** (`done`, `total`, `percent`, `last_query_id`) to the progress JSONL. All quality data is discarded at write time.
- **Lines 830-831:** Per-query results are collected in-memory via `asyncio.gather`, passed back to `run_eval`.
- **Lines 680-688:** Aggregation and canonical JSON write happen **only after all queries complete**.

**Consequence:** If the process is interrupted before line 680, **all per-query quality data is lost**. This is exactly what happened at 1100/3269. The data was computed, then thrown away.

---

## Tier 0 Scope

**Objective:** Make the eval runner interrupt-safe by persisting per-query quality evidence to disk as each query completes.

**Change location:** `eval_retrieval_runtime.py`, function `_eval_one()` (lines 812-828).

**What to add:**
1. A new `--per-query-output` CLI parameter (path to a JSONL file).
2. Inside `_eval_one()`, after computing `result` (line 812), **append the full `result` dict as one JSON line** to the per-query JSONL. Use the existing `progress_lock` for concurrency safety.
3. Ensure the per-query JSONL is independently parseable — each line is a complete per-query record.

**What NOT to touch:**
- No changes to the existing progress JSONL format (backward compatible).
- No changes to the canonical output JSON schema.
- No changes to `aggregate_metrics()` — it already works on `list[dict]`.
- No new dependencies.
- No refactoring of existing code structure.

**Estimated change:** ~15 lines of code addition. Zero lines modified.

---

## Verification Protocol (from morpheus-quality-tiers.md Tier 0 spec)

1. Run 5 queries in dry-run mode (no rerank API, local-only).
2. Verify per-query JSONL is written and each line is valid JSON with recall/mrr fields.
3. Verify aggregate metrics can be recomputed from the per-query JSONL by piping into `aggregate_metrics()`.
4. Verify that interrupting at query 3 leaves usable per-query data for queries 1-3 in the JSONL.

**Cost:** Zero. No paid API calls.

---

## Hard-Stop Analysis

| Boundary | Crossed? | Reasoning |
|---|---|---|
| New dependency | ❌ NO | Uses only `json`, `asyncio`, `Path` — all existing imports |
| Schema change | ❌ NO | Adds a new output file; does not modify existing file schemas |
| Refactor | ❌ NO | Pure addition of ~15 lines in one function; no restructuring |
| Paid API call | ❌ NO | Tier 0 runs with `--no-rerank` (local-only) |
| Reviewer lockout | ❌ NO | No relation to the rejected U1 artifact cycle |

---

## Execution Owner

**Tank** — this is QA infrastructure. Tank already identified the defect in `tank-1100-vs-3269.md` and is named as Tier 0 executor in `morpheus-quality-tiers.md`.

**Review:** Morpheus reviews the change before any paid eval (Tier 1+) is authorized.

---

## Budget Gate Reminder

- **Tier 0:** No approval needed (zero cost). ← WE ARE HERE
- **Tier 1 (50 queries):** Any team member may run.
- **Tier 2 (250 queries):** Requires Morpheus or 小龙 approval.
- **Tier 3 (3269 queries):** Requires BOTH Morpheus AND 小龙 approval.

No paid eval runs until Tier 0 passes all 4 verification checks.

---

## Supersedes

This decision formalizes the Tier 0 gate from `morpheus-quality-tiers.md` with concrete code-level scope boundaries. The quality-tiers decision remains the governing document for Tiers 1-3.
