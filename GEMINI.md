
## Required Workspace Guide

Before editing, moving files, running tests, or giving commands, read `AI_WORKSPACE_GUIDE.md`.

Key rules:

- Active backend code lives under `literature_assistant/core/`.
- Use `literature_assistant.core.python_adapter_server:app` for Uvicorn.
- Keep generated/runtime output under `workspace_artifacts/`.
- Put project plan/spec files under `docs/plans/`.
- Treat `github/` as read-only external references unless the user explicitly asks.
- Create rollback snapshots and check mature/official references before nontrivial changes.

## Squad Collaboration

This project uses squad for multi-agent collaboration. Run `squad help` for all commands and usage guide.
