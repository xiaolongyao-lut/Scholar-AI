# TASK-212 Default-Off RAGWorkflow Chat Adapter

## Facts

- Branch: `codex/gateb-goldset`
- Scope: `/api/chat` project mode only.
- Runtime flag: `INTELLIGENT_CHAT_RAGWORKFLOW_ENABLED=1`.
- Default behavior remains TASK-211 project chunk search plus `/chat/ask`.
- No real `.env` changes, no corpus/goldset/qrels/eval criteria edits, no rerank enablement, no TOLF/default chain switch.

## Mature-Solution Check

- FastAPI official response-model guidance says declared response models drive response validation, OpenAPI schema, serialization and filtering. The adapter therefore preserves the existing `IntelligentChatResponse` contract instead of adding a second response shape.
- LangChain official RAG guidance separates indexing from runtime retrieval/generation and supports using an already available search/index before retrieval and generation. The adapter follows that pattern by loading existing project chunks into local-data RAGWorkflow without changing ingestion.
- Sources checked: `https://fastapi.tiangolo.com/tutorial/response-model/` and `https://docs.langchain.com/oss/python/langchain/rag`.

## Decisions

- Keep adapter default-off behind `INTELLIGENT_CHAT_RAGWORKFLOW_ENABLED`.
- Route to RAGWorkflow only when `project_id` is present and the flag is truthy.
- Use project chunk-store chunks as local RAG data and preserve chunk provenance through `context_metadata` and `evidence_refs`.
- Skip semantic-cache embedding when RAGWorkflow has no remote rag adapter; semantic cache is an optimization, not a prerequisite for local RAG.
- Fingerprint local-data corpora with a deterministic hash instead of requiring a chunk-store manifest.

## Verification

- `.venv-1\Scripts\python.exe -m pytest tests\test_intelligent_chat_router.py tests\test_main_rag_workflow_generation.py -q` -> `14 passed`
- `.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\routers\intelligent_chat_router.py literature_assistant\core\routers\resources_router.py literature_assistant\core\main_rag_workflow.py tests\test_intelligent_chat_router.py tests\test_main_rag_workflow_generation.py` -> pass
- `frontend/ npm run generate:openapi` -> pass
- `frontend/ npm run build` -> pass
- `git diff --check` -> pass

## Rollback

- `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-053813-task212-default-off-ragworkflow-chat-adapter`
- `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-055022-task212-fix-llm-return-before-verify`

## Next

- Add a UI/contract smoke for RAGWorkflow-enabled chat if the adapter becomes a visible canary.
- Before any real rerank canary, keep no-rerank control and unique output manifest requirements.
