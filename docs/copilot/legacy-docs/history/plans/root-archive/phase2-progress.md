# Phase 2 Implementation Progress

## Completed
1. ✅ Fix graph rebuild perf: `_retrieve()` now accepts `keyword_graph` param, built once in `run_eval()`
2. ✅ Created `chunk_vector_store.py`: ChunkVectorStore class with build(), embed_query(), cosine_search()
3. ✅ Fixed `vector_score = bm25_score` in `layers/r_layer_hybrid_retriever.py`:
   - Added `_cosine_sim()` helper function
   - Added `_embed_query()` method to ContextAwareRetriever
   - `hybrid_search()` now checks chunk `embedding` field and uses real cosine sim
4. ✅ Integrated dense retrieval in `eval_retrieval_runtime.py`:
   - Added ChunkVectorStore import
   - `_retrieve()` accepts `vector_store` param, calls `_dense_retrieve()`
   - `run_eval()` builds vector store once with embedding cache
5. ✅ Created `tests/test_dense_rrf_retrieval.py` with 14 test cases

## Remaining
- ✅ All 19 tests passing
- ⏳ Update plan doc: mark Phase 2 steps [x], add implementation notes
- ⏳ Run real eval with API key to get Phase 2 metrics

## Plan Doc Update Needed
File: `c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\docs\superpowers\plans\2026-04-16-advanced-retrieval-phased-execution.md`

Replace Phase 2 steps (approx lines 190-210):
```
- [ ] **Step 1: 写失败测试（dense 不再等于 bm25）**
...code block...
- [ ] **Step 2: 实现轻量向量存储与余弦检索**
- [ ] **Step 3: 接入 RRF 融合（k=60）并保留 reranker**
- [ ] **Step 4: 跑测试并通过**
...
- [ ] **Step 5: 运行评测并验收**
...
- [ ] **Step 6: Commit**
```
Replace with all [x] checked and add implementation notes.

Also update execution status section at bottom (~line 282):
Change: `- [ ] Phase 2 未开始（目标：BGE-m3 向量检索 + RRF，解决跨语言检索）`
To: `- [x] Phase 2 已完成（...）`

## Critical File Paths
- `c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\eval_retrieval_runtime.py` - eval pipeline with 3-way RRF
- `c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\chunk_vector_store.py` - NEW dense retrieval store
- `c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\layers\r_layer_hybrid_retriever.py` - fixed vector_score
- `c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\tests\test_dense_rrf_retrieval.py` - NEW 14 test cases
- Plan doc: `c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\docs\superpowers\plans\2026-04-16-advanced-retrieval-phased-execution.md`

## Plan Doc Phase 2 Section (lines ~160-200)
Phase 2 task starts at "### Task 3: Phase 2" - needs steps marked [x]
Phase 2 execution status at bottom (~line 282): "- [ ] Phase 2 未开始" needs update

## Test Command
`.\.venv-1\Scripts\python.exe -m pytest tests/test_dense_rrf_retrieval.py tests/test_graph_keyword_retriever.py tests/test_eval_runtime.py tests/test_chunk_structure.py -v`

## Key Design
- `chunk_vector_store.py` uses numpy for vectorized cosine similarity
- Embedding cache: `output/embedding_cache/corpus_embeddings.npy`
- API: SiliconFlow BAAI/bge-m3, 1024-dim
- Graceful degradation: no API key → zero embeddings → dense path skipped
- RRF fusion now 3-way: [hybrid_hits, graph_hits, dense_hits]

## Files Changed
- `chunk_vector_store.py` (NEW)
- `eval_retrieval_runtime.py` (MODIFIED)
- `layers/r_layer_hybrid_retriever.py` (MODIFIED)
- `tests/test_dense_rrf_retrieval.py` (NEW)
