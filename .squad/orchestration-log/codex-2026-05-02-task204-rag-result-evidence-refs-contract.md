# TASK-204 RAG Result Evidence Refs Contract

## Facts

- Rollback checkpoint created before edits: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-033710-continue-rag-task204-evidence-api-contract`.
- Mature solution pattern: LangChain contextual compression keeps retriever output as documents through a compression retriever; LlamaIndex `CitationQueryEngine` returns answers with `response.source_nodes`; Haystack `ExtractiveReader` returns `ExtractedAnswer` objects after document retrieval. The shared pattern is to keep source provenance attached to the returned object, not only to rendered text or sidecar artifacts.
- Mature solution sources checked:
  - `https://docs.langchain.com/oss/python/integrations/retrievers/merger_retriever`
  - `https://developers.llamaindex.ai/python/examples/query_engine/citation_query_engine/`
  - `https://docs.haystack.deepset.ai/v2.9/docs/extractivereader`
- Local gap after TASK-202/TASK-203: `_generate_answer()` persisted `evidence_refs` to `last_answer.json` and session events, but `RAGResult` did not expose the same machine-readable references to callers.

## Decision

- Add `RAGResult.evidence_refs` as an additive dataclass field with `default_factory=list` at the end of the dataclass to preserve positional-constructor compatibility.
- Introduce `_pack_generation_evidence()` so prompt context, persisted artifacts, and returned `evidence_refs` use the same evidence packing rules.
- Add `evidence_ref_count` to generation trace for lightweight contract observability.
- Keep this slice contract-only: no retrieval ranking change, no rerank default change, no TOLF chain switch, no corpus/goldset/qrels change, no `.env` edit.

## Evidence

- Changed files:
  - `literature_assistant/core/main_rag_workflow.py`
  - `tests/test_main_rag_workflow_generation.py`
  - `docs/plans/active/2026-04-27-full-project-build-master-plan.md`
- Verification:
  - `.venv-1\Scripts\python.exe -m pytest tests\test_main_rag_workflow_generation.py tests\test_main_rag_workflow_citation.py tests\test_evidence_packer.py -q` -> `18 passed`
  - `.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\main_rag_workflow.py tests\test_main_rag_workflow_generation.py` -> pass

## Open

- `RAGResult` is currently consumed mainly by direct Python/CLI paths. If a future HTTP route exposes main RAG workflow results, bind `evidence_refs` into the Pydantic/OpenAPI schema explicitly.
- Frontend already has `evidenceRefs` parsing for writing runtime skill artifacts; direct RAG answer UI/export consumption should normalize the same field if/when that endpoint is added.

## Next

- Candidate next slices:
  - Inspect whether CLI/API layers should display or serialize `RAGResult.evidence_refs`.
  - Start a guarded, default-off rerank/TOLF canary only if it has a reversible flag and focused eval evidence.
