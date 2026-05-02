# TASK-220 IntelligentChat Env Guard

## Facts

- Scope: defensive env parsing for Intelligent Chat request handlers.
- No real API calls, no `.env` edits, no secret printing, no corpus/goldset/qrels/eval-criteria changes.
- Protected env vars:
  - `INTELLIGENT_CHAT_TOLF_CONTEXT_CANDIDATES`
  - `INTELLIGENT_CHAT_MAX_SOURCE_FILES`
  - `INTELLIGENT_CHAT_MAX_FILE_BYTES`
  - `INTELLIGENT_CHAT_DAILY_CALL_CAP`
  - `INTELLIGENT_CHAT_DAILY_BUDGET_USD`

## Decisions

- Add small local helpers instead of introducing a new dependency or broad config layer.
- Invalid positive-integer env values fall back to defaults.
- Invalid budget float env values fall back to defaults.
- Keep default TOLF selector behavior unchanged and default-off.

## Verification

- `.venv-1\Scripts\python.exe -m pytest tests\test_intelligent_chat_router.py tests\test_tolf_text_selector.py -q` -> `15 passed`
- `.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\routers\intelligent_chat_router.py tests\test_intelligent_chat_router.py` -> pass
- `git diff --check` -> no whitespace errors; Windows line-ending conversion warnings only.

## Rollback

- Checkpoint: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-233506-task220-tolf-env-guard`
- Do not restore unless the user explicitly requests rollback.

## Next

- Continue with zero-cost TOLF/RAG comparison runbook or frontend provenance display.
- Real provider-backed runs still require `env-test-discipline` role-first resolution and masked connectivity probes.
