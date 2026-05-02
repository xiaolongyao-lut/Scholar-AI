# TASK-219 IntelligentChat TOLF Context Selector

## Facts

- Scope: default-off TOLF text-only context selection for project-backed `/api/chat`.
- No real API calls, no `.env` edits, no secret printing, no corpus/goldset/qrels/eval-criteria changes.
- New production module: `literature_assistant/core/tolf_text_selector.py`.
- New opt-in envs:
  - `INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED=1`
  - `INTELLIGENT_CHAT_TOLF_CONTEXT_CANDIDATES=45`
- Default behavior remains the existing project chunk search unless the TOLF env is explicitly enabled.
- TOLF failure or empty TOLF selection falls back to the normal project chunk search.

## Mature-Solution Check

- Microsoft GraphRAG query docs were checked for the local/global/basic separation pattern; this slice keeps TOLF as an opt-in local selection stage and preserves standard chunk search as the control path.
- LightRAG/GraphRAG-style retrieval notes were checked at a high level; this slice only adds provenance-preserving context selection and avoids replacing generation or global retrieval.

## Decisions

- Put reusable text-only TOLF selector code under `literature_assistant/core` instead of importing `workspace_tests/evaluation_scripts/eval_tolf_text_pilot.py`, because tests inject that path but production runtime does not.
- Use local hashing embeddings to keep the slice zero-cost and independent of `.env` provider state.
- Use TOLF only for project context selection in `/api/chat`; RAGWorkflow adapter remains controlled by `INTELLIGENT_CHAT_RAGWORKFLOW_ENABLED`.
- Preserve `chunk_id`, `material_id`, `source_labels`, `source_hint`, and query-overlap metadata in response evidence refs.

## Verification

- `.venv-1\Scripts\python.exe -m pytest tests\test_tolf_text_selector.py tests\test_intelligent_chat_router.py -q` -> `13 passed`
- `.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\tolf_text_selector.py literature_assistant\core\routers\intelligent_chat_router.py tests\test_tolf_text_selector.py tests\test_intelligent_chat_router.py` -> pass
- `$env:RUNTIME_ENV_DISABLE_DOTENV='1'; .venv-1\Scripts\python.exe -m pytest tests\test_tolf_text_selector.py tests\test_intelligent_chat_router.py tests\test_tolf_text_pilot.py tests\test_main_rag_workflow_generation.py tests\test_evidence_packer.py tests\test_eval_runtime.py -q` -> `69 passed`
- `.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\tolf_text_selector.py literature_assistant\core\routers\intelligent_chat_router.py literature_assistant\core\layers\tolf_engine.py workspace_tests\evaluation_scripts\eval_tolf_text_pilot.py tests\test_tolf_text_selector.py tests\test_intelligent_chat_router.py tests\test_tolf_text_pilot.py` -> pass
- `git diff --check` -> no whitespace errors; Windows line-ending conversion warnings only.

## Rollback

- Checkpoint: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-231255-continue-after-task218-tolf-rag-readiness`
- Do not restore unless the user explicitly requests rollback.

## Next

- Commit TASK-219 as a focused checkpoint before continuing.
- Continue with frontend provenance display or zero-cost TOLF/RAG comparison runbook; keep default chain unchanged until evidence supports switching.
