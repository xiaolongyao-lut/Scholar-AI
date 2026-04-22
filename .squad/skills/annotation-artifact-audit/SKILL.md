---
name: "annotation-artifact-audit"
description: "Audit a reviewed annotation JSONL against a frozen pool export before qrels generation"
domain: "data-engineering"
confidence: "medium"
source: "oracle gateb phase b review 2026-04-22"
---

## Context

Use this when a reviewed annotation artifact exists in-place and must be verified for scope lock, structural safety, and downstream transform readiness before any canonical qrels/goldset mutation.

## Pattern

### 1. Freeze-coherence gate

- Compare the current annotation artifact to the frozen scope, not just to expectations in prose.
- Verify:
  - exact query count
  - exact `query_id` set
  - canonical query order if the frozen workflow depends on it
  - current file hash for audit traceability

### 2. Candidate-coverage gate

- Cross-check each query against the frozen pool export using candidate identity tuples, preferably `(doc_id, chunk_id)`.
- Reject if any query has:
  - missing candidates
  - extra candidates
  - candidate count drift from the pool export

### 3. Judgment-field contract gate

For every candidate, verify:

- `relevance` exists and is restricted to the legal label set (for Gate B: `0 | 1 | 2`)
- `judged_at` exists and has a stable timestamp shape (for Gate B: ISO UTC `YYYY-MM-DDTHH:MM:SSZ`)
- candidate list exists and is actually a list

### 4. Pathology gate

Check for blockers that will poison later qrels generation:

- duplicate query IDs
- duplicate candidate identities within a query
- conflicting repeated judgments for the same candidate identity
- missing candidate arrays or non-list candidate payloads

### 5. PASS output contract

If the audit passes, downstream working transforms should consume the reviewed annotation JSONL directly and flatten candidate rows to `(query_id, doc_id, relevance)` for qrels-shaped outputs, while preserving `chunk_id`, `judged_at`, and provenance fields in an audit-side sidecar until canonical writes are approved.

### 6. Canonical-release gate

- Treat the reviewed artifact hash and the frozen baseline hash as different roles:
  - **frozen hash** = scope lock / reproducibility anchor
  - **reviewed hash** = authoritative working source for the merge slice
- Do **not** copy reviewed fields straight into canonical outputs unless they satisfy the current validator contract.
- If audit-time fields (for example composite `source_hint` values like `graph+rrf+rerank`) exceed the canonical schema, normalize them into validator-safe canonical values or the allowed sentinel, and preserve the original values in a sidecar.
- Add any canonical-required record fields that do not exist in the reviewed artifact (for Gate B: record-level `annotator_id`) during the merge slice instead of mutating the reviewed source in place.
- Never widen the validator/schema just to accommodate audit-side convenience fields unless a separate architecture gate explicitly approves that change.

## Why this is useful

This pattern separates three questions cleanly:

1. Did the reviewed artifact stay inside the frozen slice?
2. Is every candidate judged and structurally valid?
3. Is the file safe to transform without touching canonical artifacts yet?

That keeps data review deterministic and avoids accidental scope drift during annotation-heavy phases.
