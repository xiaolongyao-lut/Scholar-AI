# TASK-210 IntelligentChat HTTP Compatibility

## Facts

- Rollback checkpoint: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-044748-task210-rag-http-schema-inspection`.
- Mature solution pattern checked before implementation:
  - FastAPI official docs use `response_model` to validate responses and generate OpenAPI JSON Schema.
  - The frontend `IntelligentChat` page calls `/api/chat`, `/api/chat/sessions`, `/api/chat/resume`, and `/api/budget/status`.
- Local mismatch found:
  - `literature_assistant/core/python_adapter_server.py` mounted `/chat/*` through `routers/chat_router.py`.
  - No current formal router mounted `/api/chat*` or `/api/budget/status`.
  - Historical squad identity docs retained the `/api/chat` UI contract, so the frontend service was not random drift.
- The existing `/chat/ask` LLM proxy already handles provider routing, retry, telemetry, and sampling resolution, so the compatibility layer should reuse it instead of duplicating provider code.

## Decision

- Add `routers/intelligent_chat_router.py` with typed Pydantic request/response models and FastAPI `response_model` contracts.
- Restore the frontend-facing endpoints:
  - `POST /api/chat`
  - `GET /api/chat/sessions`
  - `POST /api/chat/resume`
  - `GET /api/budget/status`
- Keep the first slice conservative:
  - local text context comes from request `source_paths` or `LITERATURE_SOURCE_PATHS`;
  - fast/balanced/thorough only change local chunk limits;
  - generation reuses existing `/chat/ask` logic;
  - sessions persist to runtime-state JSON with atomic replace;
  - response includes `context_metadata` and `evidence_refs`.
- Do not switch default RAG/TOLF runtime, enable rerank, modify goldset/qrels/corpus, or edit real `.env`.

## Evidence

- Changed files:
  - `literature_assistant/core/routers/intelligent_chat_router.py`
  - `literature_assistant/core/python_adapter_server.py`
  - `tests/test_intelligent_chat_router.py`
  - `frontend/src/services/intelligentChatApi.ts`
  - `frontend/src/pages/IntelligentChat.tsx`
  - `frontend/src/components/chat/MessageBubble.tsx`
  - `.env.example`
  - `docs/plans/active/2026-04-27-full-project-build-master-plan.md`
  - `.squad/orchestration-log/codex-2026-05-02-task210-intelligent-chat-http-compat.md`
- Verification:
  - `.venv-1\Scripts\python.exe -m pytest tests\test_intelligent_chat_router.py tests\test_chat_router_telemetry.py tests\test_runtime_router_contract.py -q` -> `13 passed`
  - `.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\routers\intelligent_chat_router.py literature_assistant\core\python_adapter_server.py tests\test_intelligent_chat_router.py` -> pass
  - `frontend/ npm run generate:openapi` -> success
  - `frontend/ npm run build` -> success

## Open

- This is a compatibility bridge, not the final RAG/TOLF answer chain.
- Local text selection is intentionally simple and deterministic; future work can route `/api/chat` through project chunk search, `RAGWorkflow`, or a default-off TOLF adapter after keeping a standard RAG control.
- The frontend now displays evidence refs for new `/api/chat` responses, but resumed historical messages do not reconstruct evidence refs from saved context metadata yet.

## Next

- Consider adding `project_id` support to `/api/chat` so the endpoint can use existing `/resources/chunks/search` style project chunks instead of only filesystem source paths.
- Consider TOLF default-off adapter only behind explicit switch and with standard RAG control evidence.
