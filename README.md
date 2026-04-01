# Modular Pipeline Script

Academic literature processing pipeline workspace.

## Scope

This repository is intended to track the modular pipeline code under:

- `layers/`
- numbered pipeline scripts such as `00_Batch_Process_Controller.py`
- semantic routing and focus registry tests
- key implementation documents

The following local-only content is intentionally excluded from git:

- `.env`
- `output/`
- `legacy_archive/`
- `github/`
- Python caches and local IDE metadata

## Key Files

- `layers/focus_registry.py`: canonical focus registry, dedupe, persistence
- `layers/semantic_router.py`: semantic routing over the focus registry
- `focus_registry_smoke_test.py`: end-to-end compatibility smoke tests
- `quick_focus_registry_test.py`: fast local validation
- `SEMANTIC_ROUTING_IMPLEMENTATION_PLAN.md`: implementation planning notes
- `FOCUS_REGISTRY_DESIGN.md`: data model and persistence design

## Local Validation

```powershell
python .\quick_focus_registry_test.py
python .\focus_registry_smoke_test.py
```
