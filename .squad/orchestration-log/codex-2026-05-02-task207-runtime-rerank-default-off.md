# TASK-207 Runtime Rerank Default-Off Gate

## Facts

- Rollback checkpoint created before edits: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-041221-continue-rag-task207-rerank-default-off-runtime`.
- Mature solution pattern checked before implementation:
  - LlamaIndex exposes reranking as an explicit node postprocessor stage.
  - Haystack exposes rankers as explicit pipeline components.
  - LangChain contextual compression/rerank patterns are retriever wrappers, not hidden ambient defaults.
- Local mismatch: the active plan says short-term default should remain no-rerank unless evidence-gated, but the module-level runtime retriever was constructed with `HybridRetrieverWithRerank()` whose constructor default was `use_reranker=True`.
- Risk: if `.env` contains a rerank key, runtime RAG could silently use live rerank despite the current canary verdict.

## Decision

- Add `RAG_RUNTIME_RERANK_ENABLED` as the runtime RAG opt-in switch.
- Change `HybridRetrieverWithRerank()` default constructor behavior to read that switch and default to `False`.
- Preserve explicit caller control: `HybridRetrieverWithRerank(use_reranker=True)` still enables rerank, and `use_reranker=False` still disables it.
- Do not change eval runtime `use_rerank` / `--no-rerank` controls, reranker client behavior, provider credentials, corpus/goldset/qrels, or final model-selection criteria.

## Evidence

- Changed files:
  - `literature_assistant/core/layers/r_layer_hybrid_retriever.py`
  - `tests/test_llm_provider_routing.py`
  - `.env.example`
  - `README.md`
  - `docs/plans/active/2026-04-27-full-project-build-master-plan.md`
- Verification:
  - `.venv-1\Scripts\python.exe -m pytest tests\test_llm_provider_routing.py tests\test_main_rag_workflow_generation.py tests\test_reranker.py -q` -> `40 passed`
  - `.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\layers\r_layer_hybrid_retriever.py tests\test_llm_provider_routing.py` -> pass

## Open

- `workspace_tests/evaluation_scripts/eval_retrieval_runtime.py` still has `DEFAULT_USE_RERANK=True`. That is an eval-lane decision and was intentionally not changed in this runtime slice.
- Future canary runs should set `RAG_RUNTIME_RERANK_ENABLED=1` only when the output path, trace, and rollback plan are explicit.

## Next

- Prepare a default-off rerank canary runbook/manifest guard if continuing rerank work.
- Continue TOLF adapter work only behind explicit switches and standard RAG control outputs.
