# Team Decisions Log

**Last Updated:** 2026-04-21  
**Curator:** Scribe

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

