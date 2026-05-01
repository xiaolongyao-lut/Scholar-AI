# TASK-205 RAG CLI JSON Evidence Refs

## Facts

- Rollback checkpoint created before edits: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-035824-continue-rag-task205-cli-evidence-refs`.
- Mature solution pattern checked before implementation:
  - LlamaIndex `CitationQueryEngine` exposes answer source provenance through `response.source_nodes`.
  - Haystack extractive QA keeps retrieved document/source data in answer objects.
  - LangChain retriever/compression patterns preserve document metadata through retriever outputs.
- Local gap after TASK-204: direct Python callers could read `RAGResult.evidence_refs`, but `rag_integration_entry.py ask` only printed evidence count and answer text, leaving machine consumers without stable provenance unless they read sidecar files.

## Decision

- Add explicit `ask --json-output` instead of changing the default human-readable CLI output.
- Serialize `query`, `focused_points`, `memory_hits`, `rag_evidence`, `evidence_refs`, `generated_answer`, `confidence_score`, `trace`, and `association_bundle`.
- Keep serializer defensive and JSON-safe so a completed RAG run cannot fail only because one nested value is not directly JSON serializable.
- Do not change retrieval, generation, ranking, rerank defaults, TOLF chain selection, corpus/goldset/qrels, or secrets.

## Evidence

- Changed files:
  - `literature_assistant/core/rag_integration_entry.py`
  - `tests/test_rag_integration_entry_cli.py`
  - `docs/plans/active/2026-04-27-full-project-build-master-plan.md`
- Verification:
  - `.venv-1\Scripts\python.exe -m pytest tests\test_rag_integration_entry_cli.py tests\test_text_utils.py -q` -> `11 passed`
  - `.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\rag_integration_entry.py tests\test_rag_integration_entry_cli.py` -> pass

## Open

- No active HTTP endpoint was found that directly exposes `RAGWorkflow.ask_my_literature()` results. If one is introduced, bind the same fields into a Pydantic response model and regenerate OpenAPI.
- `--json-output` is intentionally opt-in; scripts relying on current text output remain compatible.

## Next

- If continuing evidence-chain work, inspect HTTP/API surfacing first.
- If no endpoint gap exists, move to a guarded, default-off rerank/TOLF canary prep slice with reversible flags and focused eval evidence.
