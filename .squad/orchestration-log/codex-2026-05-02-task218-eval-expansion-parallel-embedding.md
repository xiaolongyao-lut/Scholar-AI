# TASK-218 Eval Expansion Parallel Embedding

## Facts

- Scope: complete Claude's in-progress expanded retrieval concurrency slice.
- Dirty handoff file was `workspace_tests/evaluation_scripts/eval_retrieval_runtime.py`.
- No real API calls were made.
- No `.env` edits, no secret printing, no corpus/goldset/qrels/eval-criteria changes.
- `ARK_EXPANSION_CONCURRENCY` default is now `5`.
- `_retrieve_with_expansion()` now starts translated dense embedding with `asyncio.create_task()` so it can overlap with the async BM25 branch before dense retrieval consumes the translated vector.

## Mature-Solution Check

- Official Python asyncio task docs were checked for `asyncio.create_task()` and task concurrency semantics: `https://docs.python.org/3/library/asyncio-task.html`.
- The implementation keeps the existing coroutine/task pattern already used in the evaluation runtime and avoids new dependencies.

## Decisions

- Preserve the split-routing contract:
  - BM25 and graph still use the original Chinese query.
  - Dense retrieval uses the translated query embedding.
  - Rerank still uses the original Chinese query.
- Add a regression test that would timeout on the previous sequential embedding path, proving hybrid async work starts before translated embedding completes.
- Do not broaden this slice into real rerank/eval execution.

## Verification

- `.venv-1\Scripts\python.exe -m pytest tests\test_eval_runtime.py -q` -> `29 passed`
- `.venv-1\Scripts\python.exe -m compileall -q workspace_tests\evaluation_scripts\eval_retrieval_runtime.py tests\test_eval_runtime.py` -> pass
- `$env:RUNTIME_ENV_DISABLE_DOTENV='1'; .venv-1\Scripts\python.exe -m pytest tests\test_run_pinned_rerank_manifest.py tests\test_evidence_packer.py tests\test_main_rag_workflow_citation.py tests\test_main_rag_workflow_generation.py tests\test_embedding_provider_resolution.py tests\test_embedding_key_probe.py tests\test_eval_runtime.py -q` -> `92 passed`
- `git diff --check` -> no whitespace errors; Windows line-ending conversion warnings only.

## Rollback

- Checkpoint: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-224754-continue-doc-plan-claude-handoff`
- Do not restore unless the user explicitly requests rollback.

## Next

- Commit TASK-215~218 documentation/test/runtime closure as one focused checkpoint.
- Continue with zero-cost eval/rerank/TOLF readiness before any provider-backed run.
