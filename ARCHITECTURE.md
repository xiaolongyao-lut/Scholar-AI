# Project Architecture Complete

**Updated**: 2026-04-12  
**Project type**: academic literature processing, RAG orchestration, writing-association, and supporting frontend tooling

## Top-level runtime map

```text
Modular-Pipeline-Script/
├─ integrated_pipeline.py           public wrapper for the classic single-paper pipeline
├─ pipeline_core.py                 classic six-layer runtime implementation
├─ batch_controller.py              batch orchestration entrypoint
├─ volume_merger.py                 merge many writing material packs into a volume bundle
├─ volume_indexer.py                volume indexing and downstream analytics helper
├─ word_generator.py                generate Word documents from material packs
├─ rag_integration_entry.py         unified CLI for ask / graphrag / autorag flows
├─ main_rag_workflow.py             workflow engine for the RAG assistant
├─ writing_resources.py             association bundle build + enrichment
├─ writing_runtime.py               writing runtime context
├─ layers/                          pipeline, retrieval, scoring, memory, recovery, and analysis layers
├─ routers/                         API routers
├─ models/                          shared data models
├─ config/                          runtime configuration
├─ tests/ and test_*.py             regression and smoke coverage
├─ frontend/                        TypeScript / React frontend
└─ presentation/                    HTML-based visual outputs
```

## Classic pipeline architecture

```text
PDF
  -> integrated_pipeline.py
  -> pipeline_core.py
  -> E-layer extraction
  -> A-layer goal/focus inference
  -> R-layer hybrid retrieval
  -> G-layer scoring and evidence synthesis
  -> P-layer Word generation
  -> output/<paper_id>/
```

Relevant files:

- `layers/e_layer_multimodal.py`
- `layers/a_layer_agent_coordinator.py`
- `layers/r_layer_hybrid_retriever.py`
- `layers/k_layer_index_builder.py`
- `layers/g_layer_academic_generator.py`
- `layers/p_layer_presentation_word.py`

## Batch and volume architecture

```text
PDF folder
  -> batch_controller.py
  -> repeated integrated pipeline runs
  -> collect material packs
  -> volume_merger.py
  -> volume_bundle_<id>.json
  -> optional volume_indexer.py / cross-paper analysis
```

Relevant files:

- `batch_controller.py`
- `volume_merger.py`
- `volume_indexer.py`
- `layers/w_layer_cross_paper_analysis.py`

## RAG and association architecture

```text
User query / API request
  -> rag_integration_entry.py or routers/
  -> main_rag_workflow.py
  -> semantic routing and retrieval
  -> grounded answer generation
  -> optional association bundle
  -> writing_resources.py / writing_runtime.py
```

Relevant files:

- `rag_integration_entry.py`
- `main_rag_workflow.py`
- `writing_resources.py`
- `writing_runtime.py`
- `layers/semantic_router.py`
- `layers/focus_registry.py`
- `layers/m_layer_mempalace_memory.py`

## Supporting subsystems

### Retrieval and scoring

- `layers/r_layer_hybrid_retriever.py`
- `layers/adaptive_weight_manager.py`
- `layers/p1_fusion_weight_calibrator.py`
- `paper_processor.py`
- `parallel_processor.py`
- `scoring_engine.py`

### Cross-paper reasoning

- `layers/p2_claim_extractor.py`
- `layers/p2_conflict_detector.py`
- `layers/p2_logic_engine.py`
- `layers/p3_causal_engine.py`
- `layers/p3_exporter.py`

### Recovery and operational tooling

- `recovery_api.py`
- `recovery_cli.py`
- `recovery_execution_engine.py`
- `recovery_metrics_exporter.py`
- `recovery_workflows.py`

## Validation surface

Key regression files for the active path:

- `test_writing_resources.py`
- `test_pipeline_router_association.py`
- `test_ragflow_integration.py`
- `test_workflow_analysis_integration.py`
- `test_word_docx_smoke.py`

Recommended smoke commands:

```powershell
c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe .\integrated_pipeline.py --help
c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe .\batch_controller.py --help
c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe .\word_generator.py --help
```

## Naming contract

- Active entrypoints use duty-driven names.
- Numbered legacy script names are historical only and should not be referenced by CI, smoke tests, or current user-facing docs.
- Wrappers such as `integrated_pipeline.py` may remain, but they should statically import the current implementation module instead of dynamically loading a legacy numbered script.
