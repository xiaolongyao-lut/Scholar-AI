# RAG And Evidence Architecture

[中文](rag-evidence-architecture.md) · [Project README](../README.en.md) · [Claude / Codex Toolbox](claude-codex-toolbox.en.md)

Scholar AI's RAG path is not a single vector search. It is a local material-to-evidence pipeline used by desktop smart reading, literature-review writing, Word export, and Claude / Codex MCP tool calls.

The core shape is: local materials become locatable chunks, then different user paths enter different retrieval surfaces. Stable tools emphasize refs and evidence packs; smart reading can combine hybrid retrieval, TOLF diffusion, Wiki expansion, and structured neighbors inside a context budget; final outputs are always condensed into refs, locators, source labels, and integrity state.

```text
PDF / Markdown / OCR materials
        |
        v
resource ingestion and text extraction
        |  project / material metadata
        |  PDF text, OCR fallback, source identity
        v
structured chunks and local indexes
        |  doc_store / chunk_store
        |  page, bbox, section_path, chunk_type
        |  embedding cache with manifest validation
        v
retrieval surfaces
        |  search_refs: stable lexical refs
        |  smart reading: hybrid + TOLF + RRF + structured siblings
        |  evidence pack: project chunks + wiki / knowledge refs
        v
bounded expansion
        |  bridge-lexicon query expansion
        |  TOLF aspect-query diffusion and evidence gate
        |  wiki linked-page expansion
        |  project + wiki weighted RRF
        |  same-section table / formula / figure siblings
        v
evidence shaping and integrity gates
        |  refs, locators, source labels, qrels status
        |  evidence_integrity_gate, context receipt
        v
reading, review writing, Word export, MCP tool calls
```

## Architecture Layers

| Layer | Code Entry | Role |
|---|---|---|
| Material ingestion and chunking | `literature_assistant/core/routers/resources_router/` | Projects, materials, PDF text extraction, structured chunks, `doc_store`, and `chunk_store` |
| Stable ref retrieval | `literature_assistant/core/routers/resources_router/endpoints_search_upload.py`, `literature_assistant/core/routers/resources_router/_search_helpers.py` | `search_refs` searches the existing chunk store read-only and returns refs, scores, locators, and source summaries without ingestion side effects |
| Smart-reading context | `literature_assistant/core/routers/intelligent_chat_router.py` | Builds answer context by session, project, material, and context budget; can combine TOLF, RRF, hybrid retrieval, and structured neighbors |
| Hybrid retrieval | `literature_assistant/core/layers/r_layer_hybrid_retriever.py`, `literature_assistant/core/hybrid_search_runtime.py` | BM25 / lexical overlap / dense embeddings / optional rerank; keeps lexical retrieval when embedding or rerank services are absent |
| TOLF diffusion | `literature_assistant/core/tolf_text_selector.py`, `literature_assistant/core/layers/tolf_engine.py`, `literature_assistant/core/tolf_bridge_lexicon_store.py` | Expands queries with bridge terms, generates aspect queries, runs spreading activation over candidates, and filters weak evidence through an evidence gate |
| Wiki and knowledge expansion | `literature_assistant/core/wiki/query.py`, `literature_assistant/core/routers/evidence_router.py`, `literature_assistant/core/source_vault.py` | Wiki-first linked-page expansion, project + wiki weighted RRF, and knowledge refs; non-project content stays behind bounded resource refs |
| Structured neighbors | `literature_assistant/core/rag_structured_sibling_inclusion.py` | When a narrative chunk is selected, optional same-section or same-page table, formula, and figure-caption siblings can be appended so numerical evidence is not lost |
| Evidence packs | `literature_assistant/core/routers/evidence_router.py`, `literature_assistant/core/evidence_pack.py` | Search results shaped into refs, chunks, page/locator metadata, source labels, coverage, and integrity status |
| Evidence graph projection | `literature_assistant/core/knowledge_graph/projection.py`, `literature_assistant/core/graph_payload.py` | Projects SmartRead sessions or Wiki graphs into session, claim, source, chunk, and derived_from / contains relations for review and navigation |
| Analysis chain | `literature_assistant/core/analysis_chain_rag_builder.py` | Question, answer, and evidence snippets rendered into a reviewable analysis chain, with deterministic fallback |

## Retrieval And Expansion Paths

| Path | When Used | Expansion Method | Boundary |
|---|---|---|---|
| `search_refs` | MCP / API callers need stable, read-only, citable refs | Lexical scoring, diverse document selection, locator coverage | Does not ingest, does not copy full body text, and does not imply rerank ran |
| Smart-reading context | Desktop Q&A, PDF reading, project-context answers | Hybrid retrieval, TOLF, RRF, structured sibling inclusion | Limited by context tier and character budget; material-scoped questions prefer the active material |
| TOLF target-oriented retrieval | Indirect evidence, mechanism/method/result evidence, or cross-lingual terms are needed | Bridge-lexicon query expansion, aspect queries, spreading activation, EvidenceGate | Candidates come from the current project chunks; sparse activation falls back to lexical grounded evidence |
| Wiki-first / joint recall | Wiki index is available and its integrity gate allows it | Linked-page expansion and project + wiki weighted RRF | Wiki refs remain bounded resources and are not written into project chunks |
| Evidence-pack build | Writing, review, and MCP evidence chains | Project refs, Wiki refs, knowledge refs, locator coverage, qrels status | Produces evidence and diagnostics; it does not replace human review of paper context |
| Evidence graph | Review SmartRead or Wiki relationships | session -> claim -> chunk -> source, plus Wiki graph relations | Projection and review surface, not a mandatory entry for every RAG query |

## Evidence Chain

| Tool Or API | Output |
|---|---|
| `literature.list_projects` / `literature.list_materials` | Locate local literature projects and materials |
| `literature.get_material_chunks` | Read page-level or structured chunks |
| `literature.search_refs` | Return readable refs, scores, locators, and source summaries |
| `literature.evidence_pack_build` | Shape project chunks, Wiki refs, and knowledge refs into an evidence pack |
| `literature.evidence_integrity_gate` | Check locator, ref, coverage, and integrity risks |
| `literature.knowledge_context_receipt` | Produce a receipt for bounded context loaded by an external model |

## Fallbacks And Boundaries

- Local lexical/text retrieval still works when embedding or rerank credentials are absent.
- Embedding cache uses manifest validation so changed models, dimensions, or chunk content do not silently reuse stale vectors.
- Rerank failures keep retrieval results and diagnostics instead of stopping the literature workflow.
- TOLF and Wiki expansion are bounded expansion layers, not unbounded corpus wandering; candidates, linked pages, context length, and integrity gates all have limits.
- `search_refs`, smart-reading context, and evidence-pack build have different goals, so one entry point's behavior should not be described as every RAG tool's behavior.
- MCP tools return redacted, size-limited, ref-bearing tool results; provider keys, local databases, and runtime config are not exposed as tool arguments.
- Evidence packs prove which materials support candidate claims; they do not replace human review of original paper text, figures, tables, or citation context.
