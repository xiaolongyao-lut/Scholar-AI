# RAG And Evidence Architecture

[中文](rag-evidence-architecture.md) · [Project README](../README.en.md) · [Claude / Codex Toolbox](claude-codex-toolbox.en.md)

Scholar AI's RAG path is not a single vector search. It is a local material-to-evidence pipeline used by desktop smart reading, literature-review writing, Word export, and Claude / Codex MCP tool calls.

```text
PDF / Markdown / OCR materials
        -> resource ingestion and text extraction
        -> structured chunks and local indexes
        -> keyword + vector + rerank hybrid retrieval
        -> refs / evidence pack / integrity gate
        -> reading, review writing, Word export, MCP tool calls
```

## Architecture Layers

| Layer | Code Entry | Role |
|---|---|---|
| Material ingestion and chunking | `literature_assistant/core/routers/resources_router/` | Projects, materials, PDF text extraction, structured chunks, `doc_store`, and `chunk_store` |
| Local retrieval | `literature_assistant/core/routers/resources_router/_search_helpers.py`, `literature_assistant/core/hybrid_search_runtime.py` | Keyword/title/content scoring and diverse chunk selection across documents |
| Vector index | `literature_assistant/core/chunk_vector_store.py` | Configured embedding calls with local embedding cache and manifest validation |
| Reranking | `literature_assistant/core/reranker_client.py`, `literature_assistant/core/rerank_runtime_config.py`, `literature_assistant/core/rerank_cache.py` | Optional rerank services with cache, budget, and fallback behavior |
| Evidence packs | `literature_assistant/core/routers/evidence_router.py`, `literature_assistant/core/evidence_pack.py` | Search results shaped into refs, chunks, page/locator metadata, sources, and integrity status |
| Analysis chain | `literature_assistant/core/analysis_chain_rag_builder.py` | Question, answer, and evidence snippets rendered into a reviewable analysis chain, with deterministic fallback |

## Evidence Chain

| Tool Or API | Output |
|---|---|
| `literature.list_projects` / `literature.list_materials` | Locate local literature projects and materials |
| `literature.get_material_chunks` | Read page-level or structured chunks |
| `literature.search_refs` | Return readable refs, chunks, scores, locators, and source summaries |
| `literature.evidence_pack_build` | Shape retrieval results into an evidence pack |
| `literature.evidence_integrity_gate` | Check locator, ref, coverage, and integrity risks |
| `literature.knowledge_context_receipt` | Produce a receipt for bounded context loaded by an external model |

## Fallbacks And Boundaries

- Local lexical/text retrieval still works when embedding or rerank credentials are absent.
- Embedding cache uses manifest validation so changed models, dimensions, or chunk content do not silently reuse stale vectors.
- Rerank failures keep retrieval results and diagnostics instead of stopping the literature workflow.
- MCP tools return redacted, size-limited, ref-bearing tool results; provider keys, local databases, and runtime config are not exposed as tool arguments.
- Evidence packs prove which materials support candidate claims; they do not replace human review of original paper text, figures, tables, or citation context.
