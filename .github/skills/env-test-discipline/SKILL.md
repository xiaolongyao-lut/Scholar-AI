---
name: env-test-discipline
description: Canonical Windows-first guidance for dynamically resolving `.env` API credentials, using provider APIs safely during tasks, test-time overrides, connectivity probes, and long-run safe configuration in this repository.
---

# Env Test Discipline

Use this skill whenever an AI task needs API credentials or provider endpoints from `.env`, changes provider routing, tests temporary overrides, runs connectivity probes, or prepares long-running API-backed work.

## Use it for

- choosing API credentials for generation/chat, embedding, rerank, gateway, eval, or connectivity tasks
- adapting when `.env` API entries are added, removed, renamed, reordered, or rotated
- debugging provider selection and API key routing
- testing `.env` parsing, grouped credential pools, or temporary config overrides
- running connectivity probes before long evals or long-running sessions
- writing or reviewing tests around `runtime_env.py`, `key_pool.py`, `reranker_client.py`, or embedding/rerank resolution
- teaching another agent how to adapt env/test handling without copying repo-specific secrets

## First principle: `.env` is a dynamic API catalog

- Treat `.env` as the current provider catalog, not a static constant baked into the agent prompt.
- Re-resolve API config at the start of each task slice and after any `.env` edit, provider failure, or user-reported key rotation.
- Do not assume the last dotenv assignment is the only usable credential. This repo intentionally supports grouped/repeated credential blocks through `key_pool.py`.
- Removed API entries must become unavailable cleanly; never keep using a stale key/base/model remembered from an earlier run.
- Added API entries should be considered only after parsing and masked connectivity checks, not by copying secrets into prompts.
- Never print, persist in logs, or summarize raw API keys. Use masked key IDs only.

## Core rules

1. **Windows first.** Use PowerShell semantics, chain commands with `;`, and invoke Python as `\.venv-1\Scripts\python.exe`.
2. **Resolve through the repo code, not agent memory.** Explicit function args win first; then `runtime_env.py`; grouped or repeated credential pools flow through `key_pool.py`.
3. **Pick the API role before picking a key.** Decide whether the task needs generation/chat, embedding, rerank, gateway, or a connectivity probe, then select from the matching role-specific variables or credential pool.
4. **Do not hot-edit `.env` for one test.** Prefer `monkeypatch.setenv()` / `delenv()` or a temporary `.env` in a temp directory.
5. **Clear caches when env state changes.** If a test, probe, or same-process task swaps `.env` roots or env vars, clear `runtime_env._repo_env`, key-pool/probe singleton state, and any provider client caches before asserting or retrying.
6. **Never print raw secrets.** Connectivity checks, failure logs, handoff notes, and agent summaries must keep keys masked.
7. **Long runs must isolate experimental state.** Use temporary cache/output paths instead of poisoning shared long-run caches when proving cold vs warm behavior.

## Runtime API usage protocol

1. **Identify the role.** Map the task to one of these roles before reading credentials:
	- generation/chat: `OPENAI_*`, `ARK_*`, `VOLCANO_*`, generic fallback names when supported
	- embedding: `EMBEDDING_*`, `SILICONFLOW_EMBEDDING_*`, `JINA_*`, provider-specific embedding blocks
	- rerank: `RERANK_*`, `SILICONFLOW_RERANK_*`, `DASHSCOPE_RERANK_*`
	- gateway/eval: role-specific env vars documented in the script or runtime being executed
2. **Read the current config.** Use `runtime_env.env_value()` / resolver functions for single active values and `key_pool.parse_env_pools()` for ordered candidate pools from repeated `.env` blocks.
3. **Validate shape before blaming the key.** Check base URL normalization, endpoint path, model name, request payload shape, and role/category inference before declaring an API key invalid.
4. **Probe safely when needed.** Use `scripts/safe_env_connectivity_check.py` or a task-specific masked probe before expensive runs. Treat `reachable_endpoint_or_payload_issue` and `reachable_but_error` as useful connectivity signals, not immediate key failures.
5. **Fail over deliberately.** On auth/rate/provider failures, move to the next credential in the matching pool when the runtime supports it. Record only provider, role, masked key, verdict, and output artifact path.
6. **React to `.env` changes.** After the user adds/deletes/updates APIs, re-run the parser/probe path. Do not reuse old in-memory values, old probe summaries, or previous candidate ordering.
7. **Stop on ambiguity.** If a credential could match multiple roles and the endpoint/model cannot disambiguate it, ask for role clarification or mark it unusable for that run rather than guessing.

## Source-of-truth files

- `literature_assistant/core/runtime_env.py` — env lookup and URL cleaning
- `literature_assistant/core/key_pool.py` — grouped/multi-credential `.env` parsing
- `literature_assistant/core/reranker_client.py` — rerank target selection and normalization
- `scripts/safe_env_connectivity_check.py` — masked connectivity probe entry point
- `tests/test_safe_env_connectivity_check.py` — probe summary and exit-code expectations
- `tests/test_key_pool.py` — grouped credential parsing expectations
- `tests/test_embedding_provider_resolution.py` — embedding/provider resolution regressions

## Test discipline

- For temporary `.env` content, `chdir()` into the temp root so repo-level loaders read the intended file.
- Clear caches before assertions if the test changes env inputs.
- Prefer tight regression tests that prove one config behavior at a time.
- If a failure looks like a bad key, first rule out malformed URL/base/model values before blaming credentials.
- Add regression coverage for add/update/delete behavior when a change affects credential parsing, role inference, or fallback order.

## Connectivity discipline

- Use `scripts/safe_env_connectivity_check.py` before expensive or long-running evals.
- Treat probe failures as signals, not verdicts; malformed base URLs and wrong endpoint shapes can look like auth problems.
- For DashScope multimodal embedding or rerank, ensure the resolved request URL matches the provider-specific service path.
- Keep probe outputs under runtime/evaluation artifacts when possible, and summarize only masked keys plus verdicts.

## When `.env` APIs change

1. Re-read `.env` through the repo parser instead of patching hardcoded agent instructions.
2. Confirm the role/category for each new or changed API block.
3. Run a masked connectivity probe if the next task depends on real network access.
4. Clear env/provider caches in the current process before rerunning tests or long tasks.
5. Update tests/docs only if variable names, role semantics, or required setup changed.
6. If an API entry was deleted, verify the task reports a clear missing-config or tries the next matching pool entry instead of silently falling back to stale state.

## Borrowing rule for other agents

This file is the canonical source. Claude, Codex, Copilot, Gemini, or other agents should borrow and adapt the workflow to their own prompt/runtime style instead of creating silent divergent forks by default.