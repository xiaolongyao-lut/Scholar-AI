# TASK-203 RAG Retrieval Source Provenance

## Facts

- User confirmed rerank/TOLF guarded trials are AI self-decision level, while restructuring-level migrations still require confirmation.
- Rollback checkpoints created before and during this slice:
  - `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-024902-rag-retrieval-source-provenance`
  - `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-025728-rag-retrieval-source-provenance-continue`
- Mature-solution pattern applied: source metadata must survive compression/fusion/rerank, matching the source-node/document-metadata provenance discipline used by LlamaIndex, LangChain Contextual Compression, and Haystack-style answer/source span flows.
- Local gap: `EvidenceReference` could persist `source_labels`, but retrieval producers did not consistently attach them before evidence packing.

## Decisions

- Add a minimal shared helper `retrieval_provenance.py` for label normalization/merge/attachment rather than duplicating string handling in every retriever.
- Keep provenance additive only: no ranking, threshold, default rerank, query expansion, corpus/goldset/qrels, or `.env` changes.
- Mark actual remote rerank as `rerank`; mark API/local fallback as `rerank_fallback` so audit tools do not confuse fallback sorting with real model rerank.
- Preserve local fallback provenance at both top-level hit and `metadata` so answer packing and UI/debug surfaces can consume the same fields.

## Evidence

- Changed files:
  - `literature_assistant/core/retrieval_provenance.py`
  - `literature_assistant/core/layers/r_layer_hybrid_retriever.py`
  - `literature_assistant/core/chunk_vector_store.py`
  - `literature_assistant/core/graph_keyword_retriever.py`
  - `workspace_tests/evaluation_scripts/eval_retrieval_runtime.py`
  - `literature_assistant/core/reranker_client.py`
  - `literature_assistant/core/main_rag_workflow.py`
  - `tests/test_retrieval_provenance.py`
  - `tests/test_dense_rrf_retrieval.py`
  - `tests/test_graph_keyword_retriever.py`
  - `tests/test_main_rag_workflow_generation.py`
  - `docs/plans/active/2026-04-27-full-project-build-master-plan.md`
- Verification:
  - `.venv-1\Scripts\python.exe -m pytest tests\test_retrieval_provenance.py tests\test_graph_keyword_retriever.py tests\test_dense_rrf_retrieval.py tests\test_main_rag_workflow_generation.py tests\test_evidence_packer.py -q` -> `42 passed`
  - `.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\retrieval_provenance.py literature_assistant\core\layers\r_layer_hybrid_retriever.py literature_assistant\core\chunk_vector_store.py literature_assistant\core\graph_keyword_retriever.py literature_assistant\core\main_rag_workflow.py literature_assistant\core\reranker_client.py workspace_tests\evaluation_scripts\eval_retrieval_runtime.py tests\test_retrieval_provenance.py tests\test_dense_rrf_retrieval.py tests\test_graph_keyword_retriever.py tests\test_main_rag_workflow_generation.py` -> pass

## Open

- This slice does not change the answer UI/export surface. It only ensures retrieval provenance arrives at the evidence layer.
- Workspace Git state remains large because the earlier layout migration introduced many tracked deletions and untracked reorganized files. A formal Git checkpoint is needed to make the layout reviewable.

## Next

- Create a formal Git checkpoint after excluding local runtime/secrets/cache artifacts.
- Continue RAG hardening with either front-end evidence reference display/export unification or default-off rerank/TOLF guarded canary.
