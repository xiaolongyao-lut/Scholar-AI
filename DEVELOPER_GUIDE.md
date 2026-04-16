# Implementation Guide v3 Phase123

This guide documents the current classic pipeline path after the naming cleanup. Numbered script names are no longer the primary entrypoints.

## Scope

The repository currently exposes three major execution paths:

1. `integrated_pipeline.py`
   Single-paper pipeline wrapper for extraction, retrieval, scoring, and Word output.
2. `batch_controller.py`
   Batch orchestrator for processing many PDFs and merging material packs into volumes.
3. `rag_integration_entry.py`
   Unified CLI for the RAG assistant and writing-association workflows.

## Core Runtime Files

### Single-paper pipeline

- `integrated_pipeline.py`: public wrapper entrypoint
- `pipeline_core.py`: classic six-layer runtime
- `layers/e_layer_multimodal.py`: extraction layer
- `layers/a_layer_agent_coordinator.py`: goal and focus inference
- `layers/r_layer_hybrid_retriever.py`: hybrid retrieval
- `layers/g_layer_academic_generator.py`: evidence scoring and material generation
- `layers/p_layer_presentation_word.py`: Word output

### Batch and volume processing

- `batch_controller.py`: batch orchestration and volume triggering
- `volume_merger.py`: merge many material packs into one volume bundle
- `volume_indexer.py`: downstream volume indexing and analysis helper
- `layers/w_layer_cross_paper_analysis.py`: cross-paper conflict and consensus analysis

### RAG and writing-association path

- `main_rag_workflow.py`: orchestration for ask/workflow mode
- `rag_integration_entry.py`: CLI entry
- `writing_resources.py`: association bundle construction and enrichment
- `writing_runtime.py`: runtime context for writing-oriented features

## Single-paper Execution Flow

```text
PDF
  -> integrated_pipeline.py
  -> pipeline_core.run_pipeline(...)
  -> E-layer extraction
  -> A-layer focus inference
  -> R-layer hybrid retrieval
  -> G-layer academic scoring
  -> P-layer Word report generation
  -> output/<paper_name>/
```

Key outputs:

- `01_full_extract.json`
- `02_hybrid_retrieval.json`
- `03_academic_scoring.json`
- `<paper_name>_report.docx`

## Batch Execution Flow

```text
PDF folder
  -> batch_controller.py
  -> repeated single-paper runs
  -> collect material packs
  -> volume_merger.py
  -> volume bundle + stats + batch logs
```

Recommended command:

```powershell
c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe .\batch_controller.py .\pdfs `
  --goal "整理该批文献的共同证据与冲突点" `
  --out .\batch_output `
  --batch-size 13 `
  --pipeline .\integrated_pipeline.py `
  --volume-script .\volume_merger.py
```

## RAG Assistant Flow

```text
User query
  -> rag_integration_entry.py
  -> main_rag_workflow.py
  -> semantic routing / retrieval / answer generation
  -> optional association bundle
```

Recommended command:

```powershell
c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe .\rag_integration_entry.py ask "总结这批文献的主要争议点"
```

## Validation Checklist

Run these commands after changing entrypoints or imports:

```powershell
c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe -m py_compile `
  .\integrated_pipeline.py `
  .\pipeline_core.py `
  .\batch_controller.py `
  .\word_generator.py `
  .\volume_merger.py `
  .\system_verification.py

c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe -m pytest -q `
  .\test_writing_resources.py `
  .\test_pipeline_router_association.py `
  .\test_ragflow_integration.py `
  .\test_workflow_analysis_integration.py `
  .\test_word_docx_smoke.py
```

CLI smoke:

```powershell
c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe .\integrated_pipeline.py --help
c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe .\batch_controller.py --help
c:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe .\word_generator.py --help
```

## Naming Policy

- Public entrypoints use duty-driven names such as `batch_controller.py` and `word_generator.py`.
- Numbered legacy script names are retained only in historical reports or backups, not in active runtime instructions.
- If a wrapper remains, the repository should internally reference the duty-driven module, not a legacy numbered filename.

## Maintenance Notes

- Keep documentation aligned with the active runtime names before changing CI or smoke tests.
- Prefer static imports for entrypoint wrappers unless dynamic loading is strictly required.
- When changing batch or volume contracts, update `system_verification.py` and the smoke tests in the same change.
- Use `sqlite_maintenance.py` for SQLite health checks, checkpointing, vacuuming, backup, and restore.
- The writing runtime and resource stores default to `output/writing_runtime_state.sqlite3` and `output/writing_resources_state.sqlite3` unless overridden by `WRITING_RUNTIME_DB_PATH` or `WRITING_RESOURCE_DB_PATH`.
