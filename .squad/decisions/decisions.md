# Team Decisions Log

**Last Updated:** 2026-04-22  
**Curator:** Scribe

---

## Gate B Canonical Merge (2026-04-22)

### Ralph: Canonical Normalization Merge — Blocker Discovery

**Date:** 2026-04-22  
**Scope:** Gate B Phase B canonical normalization merge execution  
**Status:** ⛔ BLOCKED — Contract conflict requires Morpheus decision

**Blocker Finding:**

During canonical normalization merge validation, `gateb_schema_validator.py` rejected the merged output due to a semantic conflict:

1. **Phase B Guide Rule (from Morpheus authorization):**
   - Set `no_gold=true` when a query has no `rel=2` candidates
   - Implication: `rel=1` judgments are acceptable alongside `no_gold=true`

2. **Schema Validator Rule (gateb_schema_validator.py):**
   - `no_gold=true` → ALL relevance values must be 0
   - Strict invariant: cannot coexist with any `rel=1` or `rel=2` judgments

3. **Conflict Manifestation:**
   - 6 queries (16.7%) in the reviewed annotation artifact have `no_gold=true` but retain `rel=1` judgments (no `rel=2`)
   - Both rules cannot be satisfied simultaneously without modifying the reviewed data or changing the validator

**Data Integrity Action:**

- Did NOT commit invalid canonical files
- Did NOT widen the validator without contract authority
- Restored canonical files to pre-merge scaffold state after validation failure
- Annotation artifact preserved unchanged and ready for merge retry

**Decision Required:**

Morpheus must determine:
1. Is `rel=1` allowed on `no_gold=true` queries (guide-authoritative)?
2. Or must `no_gold=true` imply all relevance = 0 (validator-authoritative)?
3. If conditional, what policy disambiguates the two rules?

**Evidence:**
- Inbox note: `.squad/decisions/inbox/ralph-canonical-normalization.md`
- Ralph blocker completion: `.squad/orchestration-log/2026-04-22T22-30Z-ralph-blocker-completion.md`
- Morpheus dispatch: `.squad/orchestration-log/2026-04-22T22-35Z-morpheus-blocker-resolution-launch.md`
- Session log: `.squad/session-log-blocker-milestone-2026-04-22.md`
- Ralph history: `.squad/agents/ralph/history.md#2026-04-22 Gate B Canonical Merge — Blocker Completion & Escalation`
- Morpheus history: `.squad/agents/morpheus/history.md#2026-04-22 Gate B Canonical Merge — Blocker Resolution Dispatch`

**Impact:**
- ⛔ Ralph: Merge retry blocked pending decision
- ✅ Other work: Trinity UI, Tank tests, Oracle validation can proceed in parallel

**Next:** Morpheus logs decision; Ralph executes merge per authorized constraints

### Morpheus: `no_gold` Canonical Semantics Decision (2026-04-22)

**Date:** 2026-04-22 (22:40Z)  
**Scope:** Resolve Phase B guide vs. canonical validator semantic conflict  
**Status:** ✅ RESOLVED — Canonical validator contract wins

**The Ruling:**

For reviewed annotation artifact (36 queries, 343 candidates):

1. **Queries with ≥1 `rel=2`** → canonical qrels populated, `no_gold=false`
2. **Queries with 0 `rel=2`** → canonical qrels empty, `no_gold=true` (rel1-only judgments → audit sidecar)
3. **No validator/schema changes** required; Phase B guide clarification optional

**Rationale:**

This is the smallest durable fix. It preserves the reviewed source (no mutation), avoids widening the validator (no code changes), and keeps canonical outputs deterministic for downstream evaluation. Allowing `rel=1` rows inside `no_gold=true` canonical records would create ambiguous mixed semantics ("no gold" + "has non-zero gold" simultaneously)—that cost is higher than preserving rel1-only evidence outside canonical outputs.

**Authority:**
- **Binding to:** Ralph's canonical merge retry execution
- **Precedence:** Canonical validator contract > Phase B guide (for this conflict context)
- **Scope:** Gate B Phase B (36 queries, 343 candidates)

**Evidence:**
- Blocker discovery: `.squad/decisions/inbox/ralph-canonical-normalization.md`
- Morpheus decision note: `.squad/decisions/inbox/morpheus-no-gold-canonical-semantics.md`
- Blocker orchestration: `.squad/orchestration-log/2026-04-22T22-30Z-ralph-blocker-completion.md`
- Resolution orchestration: `.squad/orchestration-log/2026-04-22T22-40Z-morpheus-blocker-resolution.md`
- Ralph retry launch: `.squad/orchestration-log/2026-04-22T22-42Z-ralph-canonical-merge-retry.md`
- Session log: `.squad/session-log-blocker-milestone-2026-04-22.md`

---

## Rerank Pipeline (2026-04-21)

### Morpheus: Rerank Model Upgrade Audit

**Date:** 2026-04-21  
**Scope:** Qwen3-Reranker → Qwen3-Rerank compatibility  
**Status:** ✅ APPROVED

**Decision:** Text-only reranking with `qwen3-rerank` is stable and backward-compatible. Multimodal capability (image + text) is optional and not used in current pipeline. Minimal changes required.

**Key Findings:**
- Pipeline correctly extracts raw_content (uncontextualized text) for reranking
- Embedding cache independent of reranker model; remains valid
- Token truncation (7500 tokens per doc) enforced consistently
- API contract stable; no breaking changes

**Evidence:**
- `reranker_client.py:83–95` validates raw_content priority
- `contextual_chunker.py:164–175` preserves both contextualized and raw content
- Qwen3-Rerank text-only backward-compatible with Qwen3-VL-Rerank API

**Risk:** Negligible (same vendor, same rerank endpoint, backward-compatible)

---

### Oracle: Chunk-Embedding-Rerank Pipeline Trace

**Date:** 2026-04-21  
**Requested By:** 小龙 姚  
**Status:** ✅ COMPLETE — NO ACTION REQUIRED

**Decision:** The chunk-embedding-rerank pipeline is correctly configured for text-only input. No mismatch detected between chunking and reranking inputs.

**Key Findings:**
1. **Chunks:** Stored as EnrichedChunk with `content` (contextualized) + `raw_content` (original)
2. **Embedding:** Extracts from `content` field (post-context) for semantic richness
3. **Reranking:** Extracts from `raw_content` (pre-context) to avoid prefix noise
4. **Multimodal Ready:** Pipeline extensible to image input when needed; no immediate changes required

**Evidence:**
- EnrichedChunk defined in `chunk_models.py:6–18`
- Context prefix in `contextual_chunker.py:164–175`
- Embedding extraction in `chunk_vector_store.py:42–43`
- Rerank extraction in `reranker_client.py:83–95`
- Test coverage in `tests/test_reranker.py:261–309`

**Future Multimodal Extension:** If visual reranking needed in Phase 6+:
1. Extract figures/tables from PDF during chunking
2. Add `images` field to EnrichedChunk
3. Extend _extract_document() to handle multimodal format

---

### Tank: Rerank Regression Gate for Qwen3-Rerank

**Date:** 2026-04-21  
**Scope:** Qwen3-Rerank switch validation  
**Status:** ✅ PASSED (5/5 tests)

**Decision:** Text-mode rerank request shape and document source priority (raw_content first) are fully covered and validated.

**Targeted Tests:**
- `tests/test_reranker.py::test_rerank_async_reorders_using_api` ✅
- `tests/test_llm_provider_routing.py::test_hybrid_retriever_uses_siliconflow_rerank` ✅
- `tests/test_contextual_chunker.py::test_contextual_preserves_original` ✅
- `tests/test_eval_runtime.py::test_retrieve_with_expansion_uses_translated_query_for_retrieval` ✅
- Token truncation validation ✅

**Evidence:** All 5 targeted regression tests pass; SiliconFlow flat payload format confirmed stable.

---

### Trinity: Config Alignment to Qwen3-Rerank Default

**Date:** 2026-04-21  
**Scope:** Environment, code, docs, and test alignment  
**Status:** ✅ COMPLETE (Corrected from Initial VL Direction)

**Decision:** Replace all references to `qwen3-vl-rerank` with `qwen3-rerank` as default model across:
- `.env` and `.env.example` files
- `reranker_client.py` default constant
- README and documentation
- Test fixtures and assertions

**Why:** User guidance confirmed current pipeline does not require VL (multi-modal) model. Text-only `qwen3-rerank` is sufficient and matches system design intent.

**Files Updated:**
- `.env` / `.env.example`: Model string changed
- `reranker_client.py`: DEFAULT_RERANKER_MODEL updated
- README: Documentation synced
- Test payloads: Request-shape assertions left intact

**Note on Supersession:** Earlier implementation using `qwen3-vl-rerank` was cleanly reverted. No breaking changes to tests or structure. VL capability remains available if future phases require image+text reranking.

---

## Tier Gate History (Reference)

### Ralph: Tier 1 Mini-Eval (Reference)
- Sample size: 250 queries  
- Recall@5: 0.92  
- MRR: 0.828  
- Status: Baseline established

### Ralph: Tier 2 Full Eval (Reference)
- Full corpus evaluation completed  
- Metric stability confirmed across sample sizes

### Tank: Tier 0 Proof (Reference)
- End-to-end retrieval flow validated  
- All retrieval pathways (hybrid, graph, dense) integrated

---

## Process Notes

- All inbox decisions deduplicated and consolidated here
- Cross-references maintained to original evidence files in `.squad/decisions/inbox/`
- Agent history files will be appended with relevant final notes
- No git commit required for squad metadata-only changes

