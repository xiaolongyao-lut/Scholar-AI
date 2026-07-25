# AGENTS.md

This is the public auto-load entry for coding agents working on Scholar AI.
Read `docs/ai-agent-guide.md` before editing, testing, launching, or giving
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
- Codex sidebar work is the explicit browser-path exception: use the Codex
  in-app browser / side browser to open the local Scholar AI `/agent-sidebar`
  route. Do not pursue a native Codex rendered sidebar unless an official,
  verifiable host API exists.
- Claude work stays MCP/tool-bridge first. Visible UI review uses the native
  `文献助手` desktop window, not a duplicated sidebar state chain.
- Use host tool search or deferred MCP loading when available, but keep Scholar
  AI tool names/descriptions searchable, outputs bounded, and core entry points
  obvious. Tool search is not a reason to add duplicate tools, schemas, or
  answer state.
- For resumed or new sessions, use repository docs as working memory: read the
  active plan or ledger for the task, update it when reference reading or host
  testing changes direction, and close each slice with concrete evidence
  instead of relying on chat history.
- Before nontrivial edits or runbooks, create rollback/audit records under the
  Git-ignored `docs/plans/_rollback/` directory and check official or mature
  references. Do not copy credentials, runtime databases, logs, browser
  profiles, login state, or `.env*` files into a checkpoint.
- Do not stage, commit, push, move tags, create releases, or rewrite history
  unless the user explicitly asks.

Detailed agent guide: `docs/ai-agent-guide.md`.
