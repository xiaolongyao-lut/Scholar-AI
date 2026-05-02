# TASK-215~217 Claude Commit Backfill

## Facts

- Scope: documentation/evidence backfill for already committed work after TASK-214.
- No code changes were made in this backfill log.
- No model calls, no `.env` edits, no secret printing, no corpus/goldset/qrels/eval-criteria changes.
- Current commits observed:
  - `76aadcd4 Add dated manifest materialization with atomic writes`
  - `15a7bf90 Add rank and query overlap to evidence references`
  - `942cb04e Add focused tests for evidence rank and query overlap`
  - `73e896eb Add RANK to evidence prompt and document SOURCE_LABELS`
  - `2dc721c9 Add env-test-discipline skill and provider resolution improvements`

## Decisions

- Record committed work as TASK-215, TASK-216, and TASK-217 in the master plan instead of treating it as undocumented drift.
- Keep TASK-215 as zero-cost canary preparation only; real rerank canaries still require dated manifest, dry-run, paired no-rerank control, and no final release gate self-sign.
- Keep TASK-216 as evidence/provenance hardening only; do not infer any ranking/verdict change from rank/query-overlap metadata.
- Treat `.github/skills/env-test-discipline/SKILL.md` as the canonical source for API/provider/eval credential handling. The exported catalog copy and docs are reuse surfaces, not divergent forks.

## Verification

- Commit metadata inspected with `git show --stat --oneline --name-only 76aadcd4 15a7bf90 942cb04e 73e896eb 2dc721c9`.
- Master plan updated with TASK-215, TASK-216, and TASK-217 rows.
- `$env:RUNTIME_ENV_DISABLE_DOTENV='1'; .venv-1\Scripts\python.exe -m pytest tests\test_run_pinned_rerank_manifest.py tests\test_evidence_packer.py tests\test_main_rag_workflow_citation.py tests\test_main_rag_workflow_generation.py tests\test_embedding_provider_resolution.py tests\test_embedding_key_probe.py tests\test_eval_runtime.py -q` -> `92 passed`
- `.venv-1\Scripts\python.exe -m compileall -q tools\eval\run_pinned_rerank_manifest.py literature_assistant\core\evidence_packer.py literature_assistant\core\main_rag_workflow.py literature_assistant\core\runtime_env.py literature_assistant\core\key_pool.py literature_assistant\core\reranker_client.py workspace_tests\evaluation_scripts\eval_retrieval_runtime.py tests\test_eval_runtime.py` -> pass

## Rollback

- Current Codex checkpoint: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-224754-continue-doc-plan-claude-handoff`
- Do not restore unless the user explicitly requests rollback.

## Next

- Continue with TASK-218 eval expansion concurrency cleanup and focused verification.
- Before any real provider/eval run, use `env-test-discipline`: role-first resolution, repo resolvers, masked probes, cache clearing, and isolated output paths.
