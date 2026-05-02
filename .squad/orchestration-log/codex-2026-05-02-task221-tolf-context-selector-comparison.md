# TASK-221 TOLF Context Selector Comparison

## Facts

- Scope: zero-cost comparison tool and runbook for default project chunk search vs text-only TOLF context selection.
- No real API calls, no `.env` edits, no secret printing, no corpus/goldset/qrels/eval-criteria changes.
- New tool: `tools/eval/compare_tolf_context_selector.py`.
- New runbook: `docs/plans/runbooks/tolf-context-selector-comparison.md`.
- Output is JSON and intended for local `workspace_artifacts/` reports.

## Mature-Solution Check

- GraphRAG/RAG evaluation patterns separate retrieval/context selection from generation scoring.
- This tool reports overlap and deltas between default and TOLF-selected chunks before any LLM judgment.

## Decisions

- Require caller-supplied queries JSONL and chunks JSONL so the tool does not depend on live project state or mutate resource stores.
- Reuse the production `select_tolf_context_chunks()` selector.
- Report only context-selection metrics: overlap, only-default ids, only-TOLF ids, source labels, and query-overlap tokens.
- Do not infer a Go/No-Go or default-chain switch from this tool alone.

## Verification

- `.venv-1\Scripts\python.exe -m pytest tests\test_compare_tolf_context_selector.py tests\test_tolf_text_selector.py -q` -> `6 passed`
- `.venv-1\Scripts\python.exe -m compileall -q tools\eval\compare_tolf_context_selector.py tests\test_compare_tolf_context_selector.py docs\plans\runbooks\tolf-context-selector-comparison.md` -> pass
- `git diff --check` -> pass
- `$env:RUNTIME_ENV_DISABLE_DOTENV='1'; .venv-1\Scripts\python.exe -m pytest tests\test_compare_tolf_context_selector.py tests\test_tolf_text_selector.py tests\test_intelligent_chat_router.py tests\test_tolf_text_pilot.py -q` -> `24 passed`
- `.venv-1\Scripts\python.exe -m compileall -q tools\eval\compare_tolf_context_selector.py literature_assistant\core\tolf_text_selector.py literature_assistant\core\routers\intelligent_chat_router.py tests\test_compare_tolf_context_selector.py tests\test_tolf_text_selector.py tests\test_intelligent_chat_router.py` -> pass

## Rollback

- Checkpoint: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-233905-task221-tolf-context-comparison`
- Do not restore unless the user explicitly requests rollback.

## Next

- Run the comparison against an exported project chunk JSONL under `workspace_artifacts/`.
- Any default-chain change still requires report evidence plus standard RAG control and independent gate review.
