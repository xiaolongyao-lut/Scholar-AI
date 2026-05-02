
## Required Workspace Guide

Before editing, moving files, running tests, or giving commands, read `AI_WORKSPACE_GUIDE.md`.

Key rules:

- Active backend code lives under `literature_assistant/core/`.
- Use `literature_assistant.core.python_adapter_server:app` for Uvicorn.
- Keep generated/runtime output under `workspace_artifacts/`.
- Put project plan/spec files under `docs/plans/`.
- Treat `github/` as read-only external references unless the user explicitly asks.
- Create rollback snapshots and check mature/official references before nontrivial changes.
- For dynamic `.env` API usage, env/test configuration, temporary `.env` overrides, connectivity probes, or provider-resolution regressions, prefer the canonical skill `.github/skills/env-test-discipline/SKILL.md` and `docs/superpowers/env-test-discipline.md` before inventing a Gemini-only variant.

## Squad Collaboration

This project uses squad for multi-agent collaboration. Run `squad help` for all commands and usage guide.
