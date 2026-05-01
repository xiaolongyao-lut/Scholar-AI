# Phase P1: Evidence Classifier Plugin System

You are working in `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script`.

Today is April 11, 2026.

Your mission is to implement a production-grade plugin system for evidence classifiers without expanding into API refactors, observability work, or database changes.

## Non-negotiable execution rules

1. Before editing any file, create a rollback snapshot under `.rollback_snapshots/` with a timestamped folder name and copy every file you plan to modify into it.
2. Before writing code, search official or mature sources for the relevant implementation patterns. At minimum, review:
   - `pluggy` documentation
   - lightweight Python registry / factory patterns
   - dependency injection patterns for Python services
3. Do not expand into ML model implementation, external inference, or LLM integration.
4. Prefer the smallest architecture that cleanly supports extension.
5. Keep the current synchronous execution model unless a local refactor absolutely requires otherwise.

## Preconditions

Only start this phase after P0 baseline recovery is green.

## Current repo-grounded architecture facts

These are true in the current codebase:

- `modules/paper_processor.py` directly instantiates `EvidenceClassifier` in its constructor.
- `modules/paper_processor.py` calls `self.classifier.classify_evidence(...)` directly.
- `modules/container.py` registers a classifier service, but the processor factory still creates `PaperProcessor(config)` instead of injecting the classifier.
- `modules/classifier_registry.py` does not exist yet.
- `tests/test_classifier_plugin_system.py` does not exist yet.

## Required outcome

Decouple `PaperProcessor` from a hard-coded classifier implementation and provide a safe extension path for custom classifiers.

## Scope

Expected files to create or modify:

- `modules/classifier_interface.py`
- `modules/classifier_registry.py`
- `modules/ensemble_classifier.py` only if it materially improves the example or test surface
- `modules/evidence_classifier.py`
- `modules/paper_processor.py`
- `modules/container.py`
- `tests/test_classifier_plugin_system.py`
- one concise developer guide, if helpful

## Required design

Implement a three-layer structure:

1. Interface layer
   - Define a clear classifier interface or protocol for evidence classification.
   - The current `EvidenceClassifier` must conform to it.

2. Injection layer
   - `PaperProcessor` must accept an optional classifier dependency.
   - If no classifier is provided, it should fall back to the current default implementation for backward compatibility.
   - `ContainerBuilder` must construct `PaperProcessor` using the classifier service from the container.

3. Registry layer
   - Provide a runtime registry mapping classifier names to factories.
   - Pre-register a `default` classifier.
   - Support explicit registration of custom classifiers without changing core processor code.

## Important constraints

1. Do not over-engineer this into a full plugin marketplace.
2. Do not require dynamic package discovery unless it is truly justified.
3. Do not break existing `PaperProcessor` tests or config-driven behavior.
4. Preserve deterministic behavior in current default flows.

## Acceptance criteria

All of the following must be true:

1. `PaperProcessor` no longer hard-codes the classifier as its only path.
2. The container injects the classifier into the processor.
3. A custom classifier can be registered and used in tests.
4. Backward compatibility remains intact when no custom classifier is provided.
5. New plugin-system tests pass, and existing classifier / processor tests remain green.

## Verification commands

Run these after implementation:

```powershell
& '.\.venv-1\Scripts\python.exe' -m pytest tests/test_evidence_classifier.py tests/test_paper_processor.py tests/test_classifier_plugin_system.py -q
& '.\.venv-1\Scripts\python.exe' -m pytest -q
```

## Deliverables

1. Plugin system implementation
2. Focused tests proving:
   - interface conformance
   - custom classifier injection
   - registry behavior
   - backward compatibility
3. A truthful completion report with exact test counts

## Output expectations

At the end, report:

- rollback snapshot path
- files changed
- whether the processor is now classifier-injectable
- exact passing test counts
