# TASK-213 RAGWorkflow Chat Contract Smoke

## Facts

- Scope: test-only hardening for `/api/chat` RAGWorkflow project adapter.
- The test uses FastAPI `TestClient` against the real application route.
- The test keeps project creation, doc store persistence, chunk-store loading, `load_project_chunks_for_rag()`, local-data `RAGWorkflow`, generation prompt construction, endpoint response serialization, and `/api/chat/resume` persistence in the exercised path.
- The test monkeypatches only external or noisy boundaries: LLM gateway, semantic cache, query decomposition, conversation log side effects, output path, runtime env.
- No real model call, no `.env` edit, no rerank enablement, no default-chain change, no corpus/goldset/qrels edit.

## Mature-Solution Check

- FastAPI official testing docs recommend creating a `TestClient` from the FastAPI app for application-level tests without running an external server.
- pytest official monkeypatch docs describe safely replacing attributes and environment variables for tests, with automatic undo after the test.
- Sources checked: `https://fastapi.tiangolo.com/tutorial/testing/` and `https://docs.pytest.org/en/stable/how-to/monkeypatch.html`.

## Decisions

- Keep this as a focused contract smoke rather than a paid/live model test.
- Assert provenance at multiple seams: prompt contains real `chunk_id`, response context contains `chunk_id/material_id`, response `evidence_refs` preserves source labels, and resumed session keeps evidence refs.
- Accept project chunk display prefixes in evidence text; assert the core evidence body is present instead of requiring exact raw body equality.

## Verification

- `.venv-1\Scripts\python.exe -m pytest tests\test_intelligent_chat_router.py::test_api_chat_ragworkflow_adapter_preserves_project_chunk_provenance -q` -> `1 passed`
- `.venv-1\Scripts\python.exe -m pytest tests\test_intelligent_chat_router.py tests\test_main_rag_workflow_generation.py -q` -> `15 passed`
- `.venv-1\Scripts\python.exe -m compileall -q tests\test_intelligent_chat_router.py tests\test_main_rag_workflow_generation.py` -> pass

## Rollback

- `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-055758-task213-ragworkflow-chat-contract-smoke`

## Next

- Candidate next slice: prepare no-rerank control manifest or guarded rerank canary execution preconditions.
- Alternative next slice: add a TOLF/default-off adapter contract while preserving standard RAG control.
