# Scholar AI Real Provider / API Smoke

Date: 2026-06-20

Scope: low-budget real provider/API smoke only. No product-code change, no
credential edit, no `.env` edit, no staging, commit, push, tag, release,
restore, deploy, or destructive cleanup.

## Actual Worktree

- Actual Codex worktree root:
  `C:\Users\xiao\.codex\worktrees\57a7\Modular-Pipeline-Script`
- `pwd`:
  `C:\Users\xiao\.codex\worktrees\57a7\Modular-Pipeline-Script`
- `git rev-parse --show-toplevel`:
  `C:/Users/xiao/.codex/worktrees/57a7/Modular-Pipeline-Script`
- Initial Git state: detached `HEAD (no branch)` with the broad existing
  residual-closure dirty worktree.
- Source project path from delegation:
  `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script`

Environment note:

- The Codex worktree does not contain `.\.venv-1\Scripts\python.exe`.
- The source project root contains
  `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe`.
- `AI_WORKSPACE_GUIDE.md`, `AGENTS.md`, and
  `.github/skills/env-test-discipline/SKILL.md` were absent from the Codex
  worktree and were read from the source project path.
- Real smoke execution used the source project path because the source project
  has the configured virtual environment and runtime credential/config stores.

## Required Files Read

- `AI_WORKSPACE_GUIDE.md` from source project path.
- `AGENTS.md` from source project path.
- `.github/skills/env-test-discipline/SKILL.md` from source project path.
- `docs/plans/autonomous-execution-framework.md`.
- `docs/plans/autonomous-execution-planning-playbook.md`.
- `docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md`.
- `docs/plans/scholar-ai-reference-derived-code-plan-verification-audit-2026-06-20.md`.
- `docs/plans/scholar-ai-desktop-pywebview-smoke-2026-06-20.md`.
- `docs/plans/scholar-ai-source-boundary-staging-readiness-2026-06-20.md`.
- `docs/plans/longrun-goal-state-2026-06-19.json`.
- `SOURCE_RELEASE_POLICY.md`.

Targeted code reads:

- `tests/live_api_chat_full_writing_chain_smoke.py`.
- `literature_assistant/core/runtime_env.py`.
- `literature_assistant/core/key_pool.py`.
- `literature_assistant/core/provider_probe.py`.
- `literature_assistant/core/model_config_store.py`.
- `literature_assistant/core/provider_capabilities.py`.
- `literature_assistant/core/routers/model_config_router.py`.
- `literature_assistant/core/routers/chat_router.py`.

## Rollback

- Checkpoint id:
  `20260620-193948-real-provider-api-smoke-20260620`
- Checkpoint path:
  `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-68b7fededd592df7\20260620-193948-real-provider-api-smoke-20260620`
- Create command:

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\.codex\worktrees\57a7\Modular-Pipeline-Script" --label "real-provider-api-smoke-20260620"
```

- Restore policy: restore only after explicit user rollback intent.

## Dirty Worktree Audit

- In scope for this thread:
  `docs/plans/scholar-ai-real-provider-api-smoke-2026-06-20.md`.
- Existing implementation/audit residuals, not edited by this thread:
  modified backend/frontend/product/test files and untracked allowlisted tests
  already recorded by the residual-closure, desktop, and source-boundary
  records.
- Generated runtime output from this thread:
  `workspace_artifacts/generated/output/real_provider_api_smoke/provider_tool_capability_probe_summary.json`.
- Unknown ownership: none edited. Existing broad dirty state was preserved.

## Mature / Official References

- OpenAI function/tool calling documentation:
  `https://platform.openai.com/docs/guides/function-calling`.
  Relevant rule: tool calls are structured provider protocol messages and
  should be verified separately from ordinary chat text.
- OpenAI API authentication documentation:
  `https://platform.openai.com/docs/api-reference/authentication`.
  Relevant rule: API keys are sent through Authorization headers and must not
  be logged or exposed in reports.
- Env/test discipline project skill:
  `.github/skills/env-test-discipline/SKILL.md`.
  Relevant rule: resolve credentials through project code, treat `.env` as a
  dynamic provider catalog, keep keys masked, and stop on ambiguity.
- General smoke-test practice rechecked: keep external smoke tests narrow,
  low-cost, deterministic on transport/schema status rather than exact model
  prose, and record enough telemetry for rollback/debugging without secrets.

## Config Resolution

Resolution path:

- `model_config_store.chat_store.get_resolved_field(...)` first.
- `runtime_env.env_value(...)` fallback for `CHAT_*`, `OPENAI_*`, and `ARK_*`
  generation/chat variables.
- No `.env`, credential store, key pool, or model override file was edited.
- Raw API key, Authorization header, credential id, and full credential store
  contents were not printed.

Resolved generation/chat candidate:

| role | provider | model | base_url host | masked key | verdict |
|---|---|---|---|---|---|
| generation/chat | `hhl` | `gpt-5.5` | `free.hanhanapi.top` | `sk-k...VoL6` | usable for probe |

## Smoke Selection

Primary harness reviewed:

- `tests/live_api_chat_full_writing_chain_smoke.py`.

Reason not run in this low-budget slice:

- The harness exercises `/api/chat` with a writing-chain tool loop and configures
  up to 8 MCP tool rounds. It is valuable for full acceptance, but the delegated
  budget was capped at at most 3 external API calls.
- Running the full writing-chain harness after a capability probe would exceed
  the budget. Running it first could also exceed the budget if the model
  performs multiple tool-loop rounds.

Chosen source-safe path:

- `provider_probe.probe_openai_tool_calling_capability(...)`, the existing
  project probe used by `/api/chat/tool-capability/test`.
- This path performs at most three OpenAI-compatible calls:
  1. `GET /models`
  2. ordinary low-token chat completion
  3. forced `tool_choice` function-call probe

## Command

Actual execution root:

```text
C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
```

Reason:

- The delegated Codex worktree lacks `.venv-1`.
- The source project root contains the configured runtime and existing
  credential/model stores.

Python used:

```text
C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe
```

Smoke command shape:

```powershell
@'
# Inline Python script:
# - add source project root and literature_assistant/core to sys.path
# - resolve chat provider/base_url/model/api_key through model_config_store and runtime_env
# - call provider_probe.probe_openai_tool_calling_capability(...)
# - write a redacted JSON summary under workspace_artifacts/generated/output/real_provider_api_smoke/
'@ | & 'C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe' -
```

## Result

Verdict: `passed`.

Redacted summary:

```json
{
  "role": "generation/chat",
  "provider": "hhl",
  "base_url_host": "free.hanhanapi.top",
  "model": "gpt-5.5",
  "masked_key": "sk-k...VoL6",
  "has_api_key": true,
  "probe_type": "openai_chat_completions_tool_capability",
  "api_call_budget_max": 3,
  "status": "passed",
  "api_call_count": 3,
  "models_ok": true,
  "ordinary_chat_ok": true,
  "tool_call_ok": true,
  "stage": "forced_tool_choice",
  "http_status_code": 200,
  "error_type": "",
  "provider_message_redacted": null,
  "non_empty_answer_verified": true,
  "native_tool_call_verified": true,
  "duration_ms": 7490
}
```

API call count:

- Total external API calls: `3`.
- Fallback attempts: `0`.
- Auth/rate/network failure: none observed.

Runtime output:

```text
workspace_artifacts/generated/output/real_provider_api_smoke/provider_tool_capability_probe_summary.json
```

This output remains under `workspace_artifacts/` and must not be staged.

## Capability Coverage

Verified:

- Existing real provider/model/base URL/key resolved through project runtime
  config paths.
- `/models` endpoint responded successfully.
- Ordinary low-token chat responded successfully; non-empty-answer capability
  was verified by the probe path.
- Native OpenAI-compatible forced tool call returned the named
  `capability_probe` tool call.
- Result proves `tool_call_ok=true` for the resolved provider/model endpoint
  under the current runtime configuration.

Not verified in this low-budget slice:

- Full `/api/chat` natural-prompt writing-chain execution.
- Natural prompt selected Scholar AI local tools autonomously.
- Tool content backflow into a final writing-chain answer.
- DOCX export, academic writing lint, or evidence-pack flow against the real
  provider.

Reason:

- The three-call budget was fully consumed by the explicit provider capability
  probe. A full `/api/chat` tool loop could require additional provider turns
  and would exceed the delegated stop boundary.

## Verification

- `git status --short --branch` before checkpoint: completed.
- Rollback checkpoint creation: completed.
- Source project `git status --short --branch`: broad dirty
  `main...origin/main [ahead 1]`, preserved.
- Config resolution dry run: completed with masked key only.
- Real provider capability smoke: passed with 3 external API calls.
- `git diff --check -- docs/plans/scholar-ai-real-provider-api-smoke-2026-06-20.md`:
  to run after this record is written.

## Gate Recommendation

Parent thread should update the real provider/API smoke gate to:

```text
passed_provider_tool_capability_probe
```

Do not mark the full natural-prompt writing-chain gate as passed from this
record alone. A stronger future gate can run
`tests/live_api_chat_full_writing_chain_smoke.py --prompt-mode autonomous_natural_task`
only with a larger explicit API-call budget and the same rollback/search/secret
discipline.

## Residual Risks

- Provider is a configured OpenAI-compatible endpoint, not necessarily official
  OpenAI.
- The provider passed native forced tool calling in a minimal probe, but this
  does not prove it will reliably complete long multi-round writing chains.
- The desktop gate remains `passed_after_main_rerun` with one first-run
  close-path flake recorded separately.
- The broad source/product worktree remains dirty and unstaged; this thread did
  not stage, commit, push, tag, release, restore, deploy, or clean runtime data.

## Parent Natural-Prompt Writing-Chain Attempt, 2026-06-20

The parent thread later strengthened the live harness instead of treating this
provider capability probe as end-to-end evidence.

Changes:

- `tests/live_api_chat_full_writing_chain_smoke.py` now supports
  `--probe-tool-capability`, which calls the product
  `/api/chat/tool-capability/test` route inside the same isolated runtime before
  attempting writing-chain dispatch.
- `tests/test_live_api_chat_full_writing_chain_smoke_harness.py` now verifies
  the local capability-auth header path for that preflight.
- `literature_assistant/core/evolution/secret_scan.py` now uses the
  package-qualified `literature_assistant.core.wiki.evaluation` import so
  direct-script execution cannot be shadowed by `tests/wiki`.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest -p no:cacheprovider
  tests\test_live_api_chat_full_writing_chain_smoke_harness.py
  tests\test_api_probe_semantics.py
  tests\test_api_chat_local_literature_tool_use.py -q`
  passed: `26 passed`.

Live natural-prompt result:

- Without same-runtime capability preflight, the smoke reached `/api/chat` but
  returned `verdict=no_tool_calls` and
  `stoppedReason=provider_tool_probe_failed` because the isolated runtime
  capability store had no `tool_call_ok` record.
- With `--probe-tool-capability`, the smoke failed before sending the
  writing-chain request:
  `verdict=tool_capability_probe_failed`, `stage=models`, `error=timeout`.

Updated gate:

```text
attempted_blocked_by_same_runtime_tool_capability_probe_timeout
```

This preserves the earlier `passed_provider_tool_capability_probe` claim while
making clear that full natural-prompt Scholar AI writing-chain/tool-content
backflow remains unproved.
