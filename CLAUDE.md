# CLAUDE.md

This is the public Claude Code entry for Scholar AI. Read `AGENTS.md`, then
read `docs/ai-agent-guide.md` before editing, testing, launching, or giving
commands.

Critical rules:

- Product name: `Scholar AI`; Chinese desktop/window name: `文献助手`.
- Current direction: MCP-first local research toolbox over a source checkout.
- Source desktop startup and final UI acceptance use:

```powershell
cd <repo-root>
& .\.venv-1\Scripts\python.exe .\start_desktop.py
```

- A healthy source desktop opens the native `文献助手` window and serves
  `http://127.0.0.1:8000/health`.
- Browser `localhost` / Vite pages are diagnostics only, not final desktop UI
  acceptance, unless the user explicitly asks for browser-path debugging.
- Before nontrivial edits or runbooks, create rollback/audit records outside the
  repository and check official or mature references.
- Do not stage, commit, push, move tags, create releases, or rewrite history
  unless the user explicitly asks.

Detailed agent guide: `docs/ai-agent-guide.md`.
