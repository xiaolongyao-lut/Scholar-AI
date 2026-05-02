---
description: "Dynamic .env API credential resolution, connectivity probes, provider routing, and test overrides. Canonical source: .github/skills/env-test-discipline/SKILL.md"
---

# Env Test Discipline (Claude Adapter)

> **Canonical source:** `.github/skills/env-test-discipline/SKILL.md` — read it for the full protocol.
> **Also:** `docs/superpowers/env-test-discipline.md` for extended guidance.
> This file adds Claude Code-specific adaptations only.

## When to Load

- Task needs API credentials from `.env` (generation, embedding, rerank, eval)
- Connectivity probe before long eval or paid API run
- Provider routing debugging
- `.env` entries changed since last task slice

## Claude-Specific Adaptations

### Shell: bash, not PowerShell

Claude Code uses Git Bash on Windows. Use Unix syntax:
- `grep`, `cat`, `head` for `.env` inspection (never `Select-String`, `Get-Content`)
- Forward slashes in paths
- `./.venv-1/Scripts/python.exe` for Python invocations

### Credential Resolution Order

1. Check explicit function args (highest priority)
2. `runtime_env.py` → `resolve_llm_config()` for single values
3. `key_pool.py` → `parse_env_pools()` for grouped/repeated credential blocks
4. Never hardcode keys in prompts or memory

### Connectivity Probe

```bash
# Masked probe — never print raw keys
./.venv-1/Scripts/python.exe scripts/safe_env_connectivity_check.py
```

Or inline probe (masked):
```bash
./.venv-1/Scripts/python.exe -c "
from literature_assistant.core.runtime_env import resolve_llm_config
key, url, model = resolve_llm_config(None, default_base_url='https://dashscope.aliyuncs.com/compatible-mode/v1', default_model='text-embedding-v3')
print(f'key_len={len(key) if key else 0} url={url} model={model}')
"
```

### Cost Profile Awareness

- `is_aggressive_cost_save()` gates LLM expansion/HyDE calls
- Default profile is "balanced" (all LLM calls active)
- Check `LITERATURE_AI_COST_PROFILE` env var before assuming cost behavior

### Never Do

- Print raw API keys in output, logs, or DECISION_TRAIL
- Hot-edit `.env` — use `monkeypatch.setenv()` in tests
- Assume last dotenv assignment is the only usable credential
- Reuse stale probe results from earlier in the session

## Key Source Files

- `literature_assistant/core/runtime_env.py` — env lookup
- `literature_assistant/core/key_pool.py` — grouped credential pools
- `literature_assistant/core/reranker_client.py` — rerank resolution
- `literature_assistant/core/ai_cost_profile.py` — cost profile
- `scripts/safe_env_connectivity_check.py` — masked probe
