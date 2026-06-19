# Literature Assistant Agent Source Map

This map is a required source-entry checklist for Codex, Claude, and MCP agents
working on literature review, introduction, manuscript drafting, evidence
packs, retrieval, rerank, figures, tables, equations, citations, or DOCX/LaTeX
export in this repository.

## Non-Negotiable Workflow

Before writing a replacement script, hash embedding, ad hoc reranker, parallel
PDF pipeline, or standalone DOCX exporter, inspect the local source entries
below and prove whether the existing capability is unavailable.

1. Read this file, `AI_WORKSPACE_GUIDE.md`, and the active plan under
   `docs/plans/`.
2. Use MCP tools first when available. If MCP times out or lacks a tool, switch
   to local source inspection with `rg` before concluding that the capability
   does not exist.
3. Use project-backed materials, chunks, evidence refs, writing resources, and
   controlled exports. Do not place manuscript artifacts in untracked task temp
   folders unless the active plan explicitly authorizes that diagnostic path.
4. Probe configured embedding/rerank/model status before implementing a fallback.
5. Preserve audit data: invocation surface, tool chain, retrieval diagnostics,
   figure/table/equation reference checks, and safe reasoning summaries.

## MCP And Agent Runtime

| Need | Primary Source |
| --- | --- |
| MCP tool definitions and HTTP bridge | `agent_mcp_server/src/lit_assistant_mcp/tools/runtime.py` |
| MCP stdio registration | `agent_mcp_server/src/lit_assistant_mcp/server.py` |
| Backend client, timeout, circuit breaker | `agent_mcp_server/src/lit_assistant_mcp/backend_client.py` |
| Attach to visible desktop runtime | `agent_mcp_server/src/lit_assistant_mcp/runtime_attach.py` |
| Debug-only backend launch | `agent_mcp_server/src/lit_assistant_mcp/backend_launcher.py` |
| Agent request/progress/result bridge | `literature_assistant/core/routers/agent_bridge_router.py` |
| Source-launched local tool parity for `/chat/ask` and `/api/chat` | `literature_assistant/core/routers/local_literature_tool_bridge.py` |
| Desktop runtime descriptor | `literature_assistant/core/runtime_descriptor.py` |
| Desktop launcher | `start_desktop.py` |

MCP clients should attach to the source desktop runtime when present. Headless
Uvicorn autostart is only a debug path and must not become the product
direction for writing workflows.

## Materials, Chunks, And Safe Paths

| Need | Primary Source |
| --- | --- |
| Project source-folder binding and scan-folder | `literature_assistant/core/routers/resources_router/endpoints_projects.py` |
| Shared source-folder guard | `literature_assistant/core/routers/resources_router/path_guard.py` |
| Resources router prefix and legacy compatibility | `literature_assistant/core/routers/resources_router/__init__.py` |
| Pure read chunk refs search | `literature_assistant/core/routers/resources_router/endpoints_search_upload.py` |
| Resource models | `literature_assistant/core/models/resources.py` |
| Generated/runtime path anchors | `literature_assistant/core/project_paths.py` |

Source-folder writes and scans must pass the shared guard. Agents must not set
arbitrary local paths through MCP. Use an existing project-scoped source folder
or the desktop picker flow.

## Embedding, Rerank, And Hybrid Retrieval

| Need | Primary Source |
| --- | --- |
| Local embedding fallback and status | `literature_assistant/core/local_embedding_adapter.py` |
| Local rerank fallback and status | `literature_assistant/core/local_rerank_adapter.py` |
| Vector store and embedding fallback behavior | `literature_assistant/core/chunk_vector_store.py` |
| Hybrid retriever with dense/rerank provenance | `literature_assistant/core/layers/r_layer_hybrid_retriever.py` |
| Rerank API/local fallback client | `literature_assistant/core/reranker_client.py` |
| Chat and embedding config/probes | `literature_assistant/core/routers/model_config_router.py` |
| Rerank config/probes | `literature_assistant/core/routers/rerank_config_router.py` |
| Feature flags | `literature_assistant/core/feature_flags.py` |

Important flags and probes:

- `hybrid_retrieval`: BM25 + dense + optional rerank path for chat/RAG.
- `local_rerank`: API rerank path with local loopback fallback semantics.
- `rag_local_cross_encoder_rerank`: local cross-encoder fallback path.
- `/api/embedding/local-status`: local embedding availability without loading
  weights.
- `/api/embedding/test`: configured embedding endpoint probe.
- `/api/rerank/test` and rerank config routes: configured rerank probe.

Do not implement substitute embeddings or reranking until these probes and
sources show that the configured and local adapters are unavailable for the
current workflow.

## Analysis Chain And Reasoning Audit

| Need | Primary Source |
| --- | --- |
| Shared 6-field reasoning payload | `literature_assistant/core/models/analysis_chain.py` |
| RAG analysis-chain builder | `literature_assistant/core/analysis_chain_rag_builder.py` |
| Chat integration | `literature_assistant/core/routers/chat_router.py` |
| Intelligent chat integration | `literature_assistant/core/routers/intelligent_chat_router.py` |
| MCP tool-use runner | `literature_assistant/core/mcp_runtime/tool_use_runner.py` |

The analysis chain is a safe structured reasoning summary, not private
chain-of-thought. Expose it as observation, mechanism, evidence, boundary,
counter_evidence, and next_action when the workflow needs reasoning audit.

## Writing, Evidence, Style, And Export

| Need | Primary Source |
| --- | --- |
| Writing runtime and stores | `literature_assistant/core/writing_runtime.py` |
| Writing endpoints: outline, figures, citations | `literature_assistant/core/routers/writing_router.py` |
| Evidence packs and overlap checks | `literature_assistant/core/routers/evidence_router.py` |
| Academic writing linter and audit trail | `literature_assistant/core/academic_writing_linter.py` |
| Linter HTTP route | `literature_assistant/core/routers/linter_router.py` |
| DOCX/export route | `literature_assistant/core/routers/export_router.py` |
| Resource export helpers | `literature_assistant/core/routers/resources_router/_export_helpers.py` |
| Markdown/DOCX export stats route | `literature_assistant/core/routers/resources_router/endpoints_export_stats.py` |

Writing workflows must keep figure, table, equation, citation, evidence, and
style-profile checks visible. Journal-specific requirements should flow through
style profiles or uploaded/confirmed journal specs rather than hard-coded prose
rules in an agent script.

## Chunk Package Quality And Gold Data

| Need | Primary Source |
| --- | --- |
| Chunk package audit | `literature_assistant/core/chunk_package_quality.py` |
| Review-ready chunk/goldset bundle CLI | `workspace_tests/evaluation_scripts/chunk_goldset_review_bundle.py` |
| Reviewed qrels promotion CLI | `workspace_tests/evaluation_scripts/chunk_goldset_promote_review.py` |
| Chunk package tests | `tests/test_chunk_package_quality.py` |
| Generated audit reports | `workspace_artifacts/generated/output/` |

Use chunk package audit before promoting a package to gold data. A goldset
proposal is a review candidate only; it must keep qrels and no-gold sections
visible and must not mutate the source package.

For real packages such as the AlSi10Mg review outputs, generate a review bundle
instead of editing qrels by hand:

```powershell
.\.venv-1\Scripts\python.exe workspace_tests\evaluation_scripts\chunk_goldset_review_bundle.py `
  --package "<chunk-package-dir>" `
  --output-dir "workspace_artifacts\generated\output\<review-bundle-dir>"
```

The bundle writes `chunk_quality_report.json`, `goldset_proposal.json`,
`qrels_candidate.trec`, `goldset_review_template.jsonl`,
`chunk_goldset_standards.md`, and `bundle_manifest.json`. Candidate qrels are
not canonical until a human reviewer fills the JSONL judgment template and the
promotion path records a checkpoint, old/new metrics, and a recovery path.

After human review, promote only the reviewed JSONL, never the candidate qrels
directly:

```powershell
.\.venv-1\Scripts\python.exe workspace_tests\evaluation_scripts\chunk_goldset_promote_review.py `
  --judgments-jsonl "<reviewed-goldset-jsonl>" `
  --output-qrels "<canonical-qrels-path>" `
  --manifest "<promotion-manifest-json>"
```

The promotion CLI rejects `unknown` judgments and writes canonical TREC qrels
only from reviewed rows.

## Required MCP Writing Acceptance Checks

For an MCP-assisted literature review, introduction, or manuscript section,
capture all of the following:

- Which MCP tools were called, in order.
- Whether `/api/chat` or `/chat/ask` local tool parity was used instead of
  external MCP.
- Retrieval method and diagnostics: lexical, hybrid, hybrid_rerank,
  embedding_status, rerank_status, fallback_reason, project/wiki weights.
- Evidence refs with project id, chunk id, locator/page, and read endpoint.
- Figure, table, and equation reference counts.
- Journal/style profile used for linting.
- Academic writing lint score and issues.
- Export artifact path under controlled workspace output.

## Forbidden Shortcuts

- Do not treat MCP timeout as proof that a backend capability is missing.
- Do not bypass project materials/chunks with a private JSON-only pipeline
  unless the active plan names that diagnostic explicitly.
- Do not write hash embeddings, toy rerankers, or one-off citation linters
  before checking the adapter/status sources in this file.
- Do not expose absolute source-folder paths to external MCP agents when a
  source-folder ref or basename is sufficient.
- Do not expose private chain-of-thought; use analysis-chain summaries and
  retrieval diagnostics.
