# TASK-211 Project-backed IntelligentChat

## Facts

- Rollback checkpoint: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-051430-task211-project-backed-intelligent-chat`.
- Mature pattern check: FastAPI typed `response_model`/OpenAPI contract stays the public boundary (`https://fastapi.tiangolo.com/reference/apirouter/`); RAG flow remains retrieve-then-generate with retrieved chunks preserved as provenance-bearing artifacts (`https://docs.langchain.com/oss/python/langchain/retrieval`).
- `/api/chat` now accepts optional `project_id`; when present, it validates the writing project and uses project chunk search before the LLM call.
- Project chunk provenance is preserved in `context_metadata.chunks` and `evidence_refs`: `chunk_id`, `material_id`, `title`, `section_title`, `page`, `source_labels`, and `source_hint`.
- Frontend `IntelligentChat` passes the active writing project from `WritingContext.activeProjectId` and displays the project context in the header.
- Legacy local source fallback through `source_paths` / `LITERATURE_SOURCE_PATHS` remains available.

## Decisions

- Keep this slice as an HTTP compatibility/data-path hardening task, not a default-chain migration.
- Reuse `resources_router` chunk store search instead of creating a second IntelligentChat-only index.
- Do not enable rerank, do not switch to TOLF by default, do not modify `.env`, and do not touch corpus/goldset/qrels/eval criteria.

## Verification

- `.venv-1\Scripts\python.exe -m pytest tests\test_intelligent_chat_router.py -q` -> `6 passed`.
- `.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\routers\intelligent_chat_router.py literature_assistant\core\routers\resources_router.py tests\test_intelligent_chat_router.py` -> pass.
- `frontend/ npm run generate:openapi` -> success.
- `frontend/ npm run build` -> success.
- `frontend/ npm run test -- src/pages/IntelligentChat.test.tsx` -> no matching test file exists; not a code regression.

## Open

- No final release gate signed.
- Project-backed chat currently uses lightweight project chunk scoring; default-off RAGWorkflow/TOLF adapter remains a future task with explicit control/fallback.

## Next

- Consider a default-off adapter that can route `/api/chat` through `ask_my_literature()` or TOLF while keeping standard RAG control, trace evidence, and fast rollback.
