# Scholar AI Agent Guide

This document is the public operating guide for Claude, Codex, Copilot, and
other coding agents working from a source checkout. It explains how to run,
inspect, validate, and extend Scholar AI without relying on private local
memory.

Keep this file clone-safe: no secrets, no personal machine state, no local
operator memories, and no private run logs.

## Product Identity

- Product name: `Scholar AI`.
- Chinese desktop/window name: `文献助手`.
- Active backend package: `literature_assistant/`.
- Current direction: MCP-first local research toolbox over a source checkout.
- Do not revive standalone installer, app-store, public `.mcpb`, or bundled exe
  work unless the user explicitly reopens that product direction.

## First Steps In Every Session

1. Read root `AGENTS.md`, then read this file.
2. If `AI_WORKSPACE_GUIDE.md` exists in the local checkout, read it next and
   treat it as the local operator overlay.
3. Inspect `git status --short --branch` before editing, moving files, running
   tests, staging, committing, or giving commands.
4. Before nontrivial edits, cleanup, config changes, architecture changes,
   startup/process changes, or public-doc changes, create a rollback snapshot
   outside the repository.
5. Before changing architecture, packaging, startup, import behavior, desktop
   launch, process cleanup, MCP/tool contracts, or public docs, check official
   or mature references instead of relying on memory.
6. Read target files before editing. Preserve unrelated user or agent changes.

Rollback snapshots must not be created inside the repository. Use an external
parent directory such as a sibling `_backups/Scholar-AI/<task>-<timestamp>/`.
If this checkout lives under a local `tools` directory, put rollback/audit
records under that external `tools/_backups/` tree. Do not copy credential,
token, login-state, runtime database, log, or browser-profile files into a
snapshot; record only path, size, timestamp, and intended action.

## Source Desktop Startup

For normal source usage and all final frontend/UI acceptance, start the desktop
app, not a standalone browser tab.

```powershell
cd <repo-root>
& .\.venv-1\Scripts\python.exe .\start_desktop.py
```

Expected behavior:

- A visible desktop window titled `文献助手` opens.
- The launcher starts the FastAPI backend and pywebview desktop window from the
  same source workflow.
- `http://127.0.0.1:8000/health` returns a healthy JSON response.
- Closing the desktop window should end the app process.

When an agent changes or validates frontend behavior, it should launch this
source desktop app in a visible terminal and use the native `文献助手` window as
the acceptance surface. Browser `localhost` / Vite pages are allowed for narrow
debugging, build checks, and API smoke checks, but they are not final desktop
UX evidence unless the user explicitly asks for browser-path debugging.

If a source desktop is already running, verify the existing process and health
endpoint before starting another copy. If port `8000` is occupied by an
unrelated process, do not kill it blindly; inspect the owning process and either
ask for approval or use the app's supported port/runtime configuration.

MCP stdio startup is different from frontend acceptance. The MCP wrapper should
stay protocol-clean and does not open the desktop app by default. Use the
visible `start_desktop.py` launch for source desktop work, or the documented
`-ForceLaunch` / environment opt-in only when the user explicitly wants the MCP
wrapper to reopen the desktop.

## Setup Commands

Use Windows PowerShell from the repository root unless noted.

```powershell
py -3.11 -m venv .venv-1
.\.venv-1\Scripts\python.exe -m pip install --upgrade pip
.\.venv-1\Scripts\python.exe -m pip install -e ".[desktop,dev]"
.\.venv-1\Scripts\python.exe -m pip install -r requirements-ci.txt
cd frontend
npm ci
npm run build
cd ..
.\.venv-1\Scripts\python.exe .\start_desktop.py
```

Backend-only diagnostic entry:

```powershell
.\.venv-1\Scripts\python.exe -m uvicorn literature_assistant.core.python_adapter_server:app --host 127.0.0.1 --port 8000
```

Do not suggest deprecated root scripts such as `python python_adapter_server.py`,
`python batch_controller.py`, or `python pipeline_core.py`.

## Verification Commands

Choose the smallest verification loop that proves the change.

```powershell
.\.venv-1\Scripts\python.exe .\run_literature_assistant.py paths
.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant run_literature_assistant.py sitecustomize.py tests\conftest.py
.\.venv-1\Scripts\python.exe -m pytest tests --collect-only -q
cd frontend
npm run build
npm run test -- --run
cd ..
```

For desktop work, also launch `start_desktop.py` and verify the `文献助手`
window. For MCP work, run:

```powershell
.\agent_mcp_server\bin\lit-assistant-mcp.ps1 -SelfTest
```

## Repository Layout

- `literature_assistant/core/`: active backend, FastAPI routers, retrieval,
  writing, OCR, credentials, settings, task runtime, and project resources.
- `literature_assistant.core.python_adapter_server:app`: canonical ASGI app.
- `frontend/`: React / Vite / pywebview desktop UI.
- `agent_mcp_server/`: local MCP toolbox for Claude, Codex, and other MCP
  clients.
- `agent_mcp_server/CAPABILITY_MAP.md`: tool map and source-to-tool locator.
- `docs/claude-codex-toolbox.md`: human-readable MCP toolbox guide.
- `workspace_artifacts/`: runtime/generated output; keep local-only.
- `docs/plans/`: active plans/specs; keep private unless explicitly scrubbed.
- `github/`: external reference repositories; read-only unless the user asks.
- `extension_packages/skills/` and `extension_packages/mcp/`: public optional
  Scholar AI-installable packages only.

New runtime/generated files belong under `workspace_artifacts/`. New backend
product code belongs under `literature_assistant/core/`. New frontend code
belongs under `frontend/src/`. New public user docs may go under `docs/` only
after scrub review.

## MCP Toolbox Usage

Scholar AI is MCP-first. Prefer adding or fixing MCP tools, backend HTTP
endpoints, source inspection tools, workflow artifacts, or Agent Workspace views
before inventing a packaged-app path.

The product is named Scholar AI / `文献助手`. The MCP implementation may still
use historical/internal names such as `literature_assistant`, and exposed tool
names use the `literature.*`, `source.*`, `workflow.*`, and `artifact.*`
prefixes. Treat those as stable technical namespaces, not the product name.

Typical tool flow for agents:

1. `literature.config_status` or backend `/health` to confirm the backend.
2. `literature.list_projects` to choose a `project_id`.
3. `literature.list_materials` to inspect project materials.
4. `literature.search_refs` for lightweight retrieval.
5. `literature.evidence_pack_build` for source-grounded evidence bundles.
6. `literature.evidence_integrity_gate` before using evidence in writing.
7. `source.search`, `source.read_file`, `source.read_symbols`, or
   `source.inspect_routes` for safe source inspection.

The MCP server must not receive raw provider API keys. Model and credential
configuration belongs in the local Scholar AI backend/desktop settings. Tool
outputs should remain redacted, bounded, and reference-bearing.

## Literature Ingestion And Chunks

Use the same `project_id` for the same research topic. Adding new PDFs to an
existing research project should add new `material_id` records and per-material
chunks into that project's existing doc/chunk stores. Retrieval then searches
across all materials in the project.

Supported operational paths:

- User path: open `文献助手`, choose the existing project, upload PDFs or put
  them in the project's bound source folder, then scan/import.
- Agent/MCP path: list projects, select the existing `project_id`, trigger the
  project-folder scan or relevant ingestion endpoint/tool, then verify with
  `literature.list_materials`, `literature.get_material_chunks`, and
  `literature.search_refs`.

Do not hand-edit chunk JSONL files as a shortcut. If the same paper changed and
needs refresh, prefer an explicit delete-and-reimport or implement a tested
source-fingerprint-aware refresh/upsert path. Raw single-chunk append is not a
safe public workflow unless a dedicated endpoint/tool and tests exist.

## Coding Rules

- Match existing patterns and ownership boundaries.
- Use typed Python public functions and typed TypeScript. Avoid `any`; use
  `unknown` plus type guards when shape is uncertain.
- Validate external inputs at API, filesystem, process, and MCP boundaries.
- Keep edits surgical. Do not refactor adjacent code unless required.
- Comments should explain why, not narrate obvious steps.
- Public backend responses should use existing Pydantic models and route-family
  error envelope conventions.
- New SmartRead frontend work should use `Conversation` and `MessageRenderer`;
  `MessageBubble` is compatibility-only.
- New SmartRead API work should prefer `/api/chat` or `/api/chat/stream`;
  `/chat/ask` is compatibility-only.

## Public Source Boundary

Before making anything public, read `SOURCE_RELEASE_POLICY.md`.

Never commit secrets, `.env*`, credential stores, runtime tokens, local MCP
client configs, browser profiles, logs, runtime databases, generated archives,
`workspace_artifacts/`, `workspace_references/`, local plans, or private agent
state.

`AGENTS.md` and this guide are public and should stay focused on clone-safe
instructions for agents. Personal operator rules belong in local ignored files
such as `AI_WORKSPACE_GUIDE.md`, `AGENTS.local.md`, `CLAUDE.local.md`, or
user-level agent memory.

## Git Rules

- Do not stage, commit, push, move tags, create releases, or rewrite history
  unless the user explicitly asks.
- When staging is requested, use explicit paths; do not use `git add .`.
- Before commit, run `git diff --cached --check` and
  `git ls-files -ci --exclude-standard`.
- Before push or release work, inspect the remote-facing tree, release/tag
  target, and public README/docs, not just local status.

## When Giving Commands To A User

Include the required preflight in runbooks:

1. Create rollback/audit records outside the repository.
2. Check official or mature references for the risky part of the operation.
3. Run commands from the repository root unless a command states otherwise.
4. For frontend/UI verification, launch `.\.venv-1\Scripts\python.exe .\start_desktop.py`
   and use the native `文献助手` window for final acceptance.
