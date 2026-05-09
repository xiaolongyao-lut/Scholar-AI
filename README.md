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
- `eval_retrieval_runtime.py`: retrieval evaluation runner (supports `--progress`, `--per-query-output`, and non-secret `--rerank-trace-output` JSONL)

## Evidence Scoring Package

The scoring subsystem is versioned in this repository under `modules/` and `tests/`.

Core runtime modules:

- `modules/configuration_manager.py`: loads scoring thresholds, multipliers, and goal mappings
- `modules/evidence_classifier.py`: evidence typing, quality scoring, and keyword extraction
- `modules/paper_processor.py`: per-paper scoring and aggregation
- `modules/parallel_processor.py`: deterministic parallel orchestration for scoring jobs
- `modules/container.py`: dependency wiring for classifier and scorer injection

Verification coverage for the package lives under `tests/`, including classifier, processor, plugin wiring, parallel execution, and observability behavior.

## Optional LLM Mode

### Quick Setup (No LLM Required)

By default, the pipeline **does not require OpenAI** or any LLM. Run immediately:

```bash
python batch_controller.py c:\Users\xiao\Desktop\wenxianku
```

Check the output JSON for `"llm_status": "disabled_missing_dependency"` — this is normal and expected.

### Enable LLM-Enhanced Mode

If you want AI-powered analysis (claim mining, mechanism extraction, etc.):

1. **Install OpenAI client:**
   ```bash
   pip install openai
   ```

2. **Get API Key:**
   - Sign up at https://platform.openai.com
   - Create an API key and copy it

3. **Configure .env:**
   ```
   OPENAI_API_KEY=sk-your-key-here
   OPENAI_BASE_URL=https://api.openai.com/v1
   OPENAI_MODEL=gpt-4o-mini
   ```

4. **Run pipeline:**
   ```bash
   python batch_controller.py c:\Users\xiao\Desktop\wenxianku
   ```

Check output JSON for `"llm_status": "enabled"`.

### LLM Status Field Reference

- `"enabled"`: All LLM features active.
- `"disabled_missing_dependency"`: `openai` library not installed → `pip install openai`
- `"disabled_missing_api_key"`: Library present, but no API key → Fill .env and restart
- `"disabled_by_config"`: User explicitly disabled via `enable_llm=False`

### Performance & Cost

| Mode | Speed | Cost | Quality |
|------|-------|------|---------|
| **With LLM** | ~2-5s per PDF | ~$0.01-0.05 per PDF | High (GPT enrichment) |
| **Without LLM** | ~0.5-1s per PDF | Free | Good (rule-based) |

## Retrieval Notes

- The retrieval path already chunks documents before ranking: `output\chunk_store\*.json` is loaded in `eval_retrieval_runtime.py`, and dense embeddings are built/cached via `ChunkVectorStore.build(...)`.
- Rerank model resolution defaults to `qwen3-rerank`. Runtime RAG keeps rerank default-off unless `RAG_RUNTIME_RERANK_ENABLED=1` or a caller explicitly constructs `HybridRetrieverWithRerank(use_reranker=True)`, while eval scripts keep their explicit `--no-rerank` / `use_rerank` controls.
- Intelligent Chat can trial text-only TOLF context selection with `INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED=1`; it is default-off, uses local hashed embeddings, keeps project chunk provenance, and falls back to the normal project chunk search when TOLF yields no context.
- `DASHSCOPE_*` settings keep the DashScope request shape, while `SILICONFLOW_RERANK_*` still use the existing SiliconFlow request shape.
- Rerank budget guard envs: `RERANK_DAILY_CALL_CAP` and `RERANK_DAILY_TOKEN_CAP` are hard fallback caps; `RERANK_DAILY_BUDGET_USD` is telemetry-only soft warning.

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

`skill-flow` visual integration is generated from canonical repo-local skills under `.github/skills/*/SKILL.md` into the local export catalog `skills/catalog/`.

Canonical authored skills live under `.github/skills/`. The new `env-test-discipline` skill is the reference pattern for dynamic `.env` API usage, provider role selection, temporary test overrides, connectivity probes, and Windows-first long-run safety; other AI runtimes should borrow or adapt it instead of silently maintaining separate divergent copies.

```powershell
pwsh -File .\skill_sync_bridge.ps1
python -X utf8 .\skills\skill_flow_adapter.py --strict
```

`skills\skill_flow_adapter.py` is a thin CLI wrapper over `literature_assistant/core/skills/skill_flow_adapter.py`. It mirrors repo-local `SKILL.md` files into `skills/catalog/` and writes `.skill-flow-export.json`. `--strict` is the fail-closed verification mode for malformed frontmatter or duplicate slugs.

`skill_sync_bridge.ps1` will:

- create a rollback snapshot under `.rollback_snapshots/`
- export or mirror canonical repo-local `SKILL.md` entries from `.github/skills/` into `skills/catalog/`
- verify bridge health through the official `skill-flow bridge --json` protocol using a machine-readable `doctor` probe
- write a bridge doctor snapshot to `skills/catalog/.skill-flow-bridge-doctor.json`

If you want to adapt the env/test guidance for Claude, Codex, Copilot, Gemini, or another runtime, start from:

- `.github/skills/env-test-discipline/SKILL.md`
- `docs/superpowers/env-test-discipline.md`

## Retained Documents

- `GETTING_STARTED.md`: usage-oriented walkthrough for the classic pipeline flow
- `DEVELOPER_GUIDE.md`: long-form implementation guide for the classic and RAG entrypoints
- `ARCHITECTURE.md`: current runtime and subsystem architecture map
- `frontend_design.md`: canonical frontend design spec for the writing-centered light glassmorphism UI
- `NAMING_AND_ARCHIVE_POLICY.md`: repository naming, archive, and AI-generated document rules
- `FOCUS_REGISTRY_DESIGN.md`: focus registry schema and persistence design
- [semantic_routing_plan](docs/history/plans/2026-04-12_semantic-routing-plan.md): historical semantic routing design and evolution notes
- `docs/history/README.md`: archive layout for historical reports, plans, prompts, and diagnostics

