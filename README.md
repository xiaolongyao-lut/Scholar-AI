# Modular Pipeline Script

Academic literature processing and retrieval workspace for the modular pipeline, semantic routing, and RAG integration stack.

## Scope

This repository tracks:

- numbered pipeline scripts such as `00_Batch_Process_Controller.py`
- reusable layers under `layers/`
- focus registry and semantic routing
- RAGFlow / GraphRAG / AutoRAG integration entrypoints and tests

Local-only or generated content should stay outside git, especially:

- `.env`
- `output/`
- `legacy_archive/`
- Python caches and local IDE metadata

## Key Entry Points

- `main_rag_workflow.py`: primary RAG workflow orchestration
- `rag_integration_entry.py`: unified CLI entry for `ask`, `graphrag`, and `autorag-generate`
- `config/rag_integration_config.yaml`: integration configuration
- `layers/focus_registry.py`: canonical focus registry, dedupe, and persistence
- `layers/semantic_router.py`: semantic routing over the focus registry

## Validation

```powershell
python -X utf8 .\quick_focus_registry_test.py
python -X utf8 .\focus_registry_smoke_test.py
python -X utf8 -m unittest .\test_ragflow_integration.py .\test_adapter_improvements.py -v
python -X utf8 .\rag_integration_entry.py --help
```

## Retained Documents

- `QUICK_START_v3.md`: usage-oriented walkthrough for the classic pipeline flow
- `IMPLEMENTATION_GUIDE_v3_Phase123.md`: long-form implementation guide for the v40 pipeline
- `FOCUS_REGISTRY_DESIGN.md`: focus registry schema and persistence design
- `SEMANTIC_ROUTING_IMPLEMENTATION_PLAN.md`: semantic routing design and evolution notes
