# Env Test Discipline

`env-test-discipline` is the canonical repository-local skill for dynamic `.env` API usage during task execution, testing, eval prep, and long-running provider work.

## Source of truth

- Canonical skill: `.github/skills/env-test-discipline/SKILL.md`
- Export path: `skills/catalog/env-test-discipline/SKILL.md`
- Sync entrypoint: `skills/skill_flow_adapter.py`
- Bridge entrypoint: `skill_sync_bridge.ps1`

## What other agents should borrow

Keep these repo facts intact when adapting the skill for another agent runtime:

1. This repo is Windows-first and uses `.venv-1\Scripts\python.exe`.
2. Env resolution flows through `literature_assistant/core/runtime_env.py`.
3. Grouped or repeated credential blocks flow through `literature_assistant/core/key_pool.py`.
4. `.env` must be treated as a dynamic API catalog: re-read it after API add/update/delete operations, provider failures, or user-reported key rotations.
5. API selection starts by role: generation/chat, embedding, rerank, gateway/eval, or connectivity probe.
6. Safe probe checks must mask secrets and should use `scripts/safe_env_connectivity_check.py`.
7. Tests or same-process tasks that swap `.env` content must clear env/key-pool/probe caches before asserting behavior or retrying.

## What each agent may adapt

- response style
- prompt scaffolding
- how the agent phrases warnings or preflight notes
- whether the agent prefers repo-local skill discovery or user-level imported catalogs

## What should not diverge silently

- Windows shell rules (`;`, not `&&`; project venv path, not system `python`)
- secret masking requirements
- dynamic re-resolution after `.env` changes
- role-first credential selection instead of “use whatever key appears last”
- long-run cache isolation guidance
- the rule that probe failures are not enough to blame API keys before checking URL/model/request-shape issues

## Recommended reuse pattern

1. Read the canonical skill.
2. At task start, re-parse the current `.env` state instead of relying on prior chat context.
3. Copy only the agent-specific framing you actually need.
4. Keep file references and safety rules aligned with the repo.
5. If an agent-specific fork becomes materially different, document why instead of drifting silently.

## Suggested validation anchors

- `tests/test_safe_env_connectivity_check.py`
- `tests/test_key_pool.py`
- `tests/test_embedding_provider_resolution.py`
- `tests/legacy_root/test_skill_flow_adapter.py`

## Notes

This document exists so Claude/Codex/Copilot/Gemini can borrow one stable pattern without this repository having to maintain four separate env-safety skills by default. One good source beats four slightly-wrong copies — fewer hydras, fewer headaches.
