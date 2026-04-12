# Modular Pipeline Script

Academic literature processing and retrieval workspace for the modular pipeline, semantic routing, and RAG integration stack.

## Scope

This repository tracks:

- duty-driven scripts such as `batch_controller.py` and `pipeline_core.py`
- reusable layers under `layers/`
- evidence scoring and batch-processing modules under `modules/`
- focus registry and semantic routing
- RAGFlow / GraphRAG / AutoRAG integration entrypoints and tests

Local-only or generated content should stay outside git, especially:

- `.env`
- `output/`
- `.rollback_snapshots/`
- `legacy_archive/`
- Python caches and local IDE metadata

## Key Entry Points

- `main_rag_workflow.py`: primary RAG workflow orchestration
- `rag_integration_entry.py`: unified CLI entry for `ask`, `graphrag`, and `autorag-generate`
- `config/rag_integration_config.yaml`: integration configuration
- `layers/focus_registry.py`: canonical focus registry, dedupe, and persistence
- `layers/semantic_router.py`: semantic routing over the focus registry
- `run_paper_scoring.py`: CLI entry point for batch evidence scoring
- `modules/paper_processor.py`: paper-level evidence aggregation and scoring
- `modules/parallel_processor.py`: deterministic parallel batch scoring
- `config/scoring_rules.json`: default scoring configuration used by `modules.configuration_manager`

## Evidence Scoring Package

The scoring subsystem is versioned in this repository under `modules/` and `tests/`.

Core runtime modules:

- `modules/configuration_manager.py`: loads scoring thresholds, multipliers, and goal mappings
- `modules/evidence_classifier.py`: evidence typing, quality scoring, and keyword extraction
- `modules/paper_processor.py`: per-paper scoring and aggregation
- `modules/parallel_processor.py`: deterministic parallel orchestration for scoring jobs
- `modules/container.py`: dependency wiring for classifier and scorer injection

Verification coverage for the package lives under `tests/`, including classifier, processor, plugin wiring, parallel execution, and observability behavior.

## Validation

```powershell
python -X utf8 .\quick_focus_registry_test.py
python -X utf8 .\focus_registry_smoke_test.py
python -X utf8 -m unittest .\test_ragflow_integration.py .\test_adapter_improvements.py -v
python -X utf8 .\rag_integration_entry.py --help
python .\integrated_pipeline.py --help
python .\batch_controller.py --help
python -m pytest .\tests\test_evidence_classifier.py .\tests\test_paper_processor.py -q
python -m pytest .\tests\test_parallel_processor.py .\tests\test_scoring_plugin_system.py -q
```

## Skill Flow Integration

`skill-flow` visual integration is wired through the local export catalog under `skills/catalog/`.

```powershell
pwsh -File .\skill_sync_bridge.ps1
python -X utf8 .\skills\skill_flow_adapter.py --strict
```

`skill_sync_bridge.ps1` will:

- create a rollback snapshot under `.rollback_snapshots/`
- export or mirror local `SKILL.md` entries into `skills/catalog/`
- sync the source through the official `skill-flow bridge --json` protocol instead of editing state files directly
- register a repo-scoped custom target at `skills/imported/skill-flow/` for later imports

## Retained Documents

- `GETTING_STARTED.md`: usage-oriented walkthrough for the classic pipeline flow
- `DEVELOPER_GUIDE.md`: long-form implementation guide for the classic and RAG entrypoints
- `ARCHITECTURE.md`: current runtime and subsystem architecture map
- `NAMING_AND_ARCHIVE_POLICY.md`: repository naming, archive, and AI-generated document rules
- `FOCUS_REGISTRY_DESIGN.md`: focus registry schema and persistence design
- `SEMANTIC_ROUTING_IMPLEMENTATION_PLAN.md`: semantic routing design and evolution notes
- `docs/history/README.md`: archive layout for historical reports, plans, prompts, and diagnostics

