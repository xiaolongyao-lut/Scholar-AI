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
   under the Git-ignored `docs/plans/_rollback/` directory.
5. Before changing architecture, packaging, startup, import behavior, desktop
   launch, process cleanup, MCP/tool contracts, or public docs, check official
   or mature references instead of relying on memory.
6. For sidebar or agent-host work, read the "Agent Host UI Direction" and
   "MCP Tool Loading And Context Budget" sections in this guide before editing.
7. Read the "Session Continuity And Working Habits" section before resuming a
   prior plan, continuing after compaction, or starting a new agent-host slice.
8. Read target files before editing. Preserve unrelated user or agent changes.

Rollback snapshots and audit records for this checkout belong under
`docs/plans/_rollback/<timestamp>-<task>/`. The entire `docs/` tree is ignored
by the repository's current Git rules, so these local recovery records stay
next to the active plans without entering a commit. Copy only the smallest
source, test, config, and plan set needed for recovery. Do not copy credential,
token, login-state, runtime database, log, browser-profile, project-data, or
`.env*` files into a snapshot; record only path, size, timestamp, and intended
action when one of those files is relevant.

## Session Continuity And Working Habits

Treat repository docs as the durable memory for new or compacted sessions. Do
not depend on hidden chat history for product direction, host capability
status, or implementation order.

Before repeating reference exploration, search the existing plan and ledger
files with `rg`. If the task involves the Codex/Claude sidebar bridge, read:

- `docs/plans/codex-sidebar-scholar-ai-bridge-draft-2026-07-06.md`
- `docs/plans/codex-sidebar-widget-reference-ledger-2026-07-07.md`

When reference reading, host testing, or user feedback changes direction,
record the result in the active plan, reference ledger, or repository-local audit
before moving on. A useful record names the file, tool, command, screenshot,
host surface, or behavior that supports the conclusion.

Work in small verifiable slices. Each completed slice needs one matching piece
of evidence: a test command, MCP tool result, receipt read-back, host capability
record, screenshot, or explicit blocked reason. Do not write unverified host
capability as completed work.

For frontend or agent-sidebar work, check the experience from two views before
closing the slice:

- frontend/operator view: layout, state transitions, errors, responsiveness,
  reuse of existing components, and no duplicated state chain;
- user view: the user can ask a question, read the answer, see evidence status,
  recover from offline/degraded states, and continue in the intended host
  surface.

Keep notes as the work proceeds. If a reference repository, host behavior, or
tool contract has already been inspected, update the ledger instead of
re-reading the same material in the next session.

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

Codex agent-sidebar work is the explicit browser-path exception. For that
surface, use the Codex in-app browser / side browser to open the local
Scholar AI `/agent-sidebar` route and verify the narrow agent UI there. This
does not change final acceptance for the native `文献助手` desktop.

If a source desktop is already running, verify the existing process and health
endpoint before starting another copy. If port `8000` is occupied by an
unrelated process, do not kill it blindly; inspect the owning process and either
ask for approval or use the app's supported port/runtime configuration.

MCP stdio startup is different from frontend acceptance. The MCP wrapper should
stay protocol-clean and does not open the desktop app by default. Use the
visible `start_desktop.py` launch for source desktop work, or the documented
`-ForceLaunch` / environment opt-in only when the user explicitly wants the MCP
wrapper to reopen the desktop.

## Agent Host UI Direction

Codex does not own a separate native Scholar AI sidebar path in this project.
The current Codex visual surface is a local web route, `/agent-sidebar`, opened
inside the Codex in-app browser / side browser. Build it as a narrow agent
panel, not as a squeezed copy of the full `/dialog` desktop workbench.

The `/agent-sidebar` route must reuse the existing Scholar AI backend,
SmartRead/chat/evidence components, receipts, qrels/gate state, revalidation,
read-evidence, and answer write-back path where those exist. Do not create a
second answer chain, schema family, state store, or history model just because
the view is narrow.

Claude work remains MCP/tool-bridge first. For visible review and acceptance,
use the native `文献助手` desktop window. Claude MCP Apps, inline widgets, or
rendered resources may be tested when a host explicitly supports them, but they
do not replace the desktop review path and should not drive a duplicate UI
architecture.

If a host later exposes a verified third-party native sidebar/panel API, record
the evidence in `docs/plans/` before changing this direction. Until then,
native Codex/Claude sidebar work stays parked; the deliverable surface is the
Codex in-app browser route plus the existing MCP/desktop bridge.

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
window. For Codex `/agent-sidebar` work, also open the local route in the
Codex in-app browser / side browser and record visual or interaction evidence.
For MCP work, run:

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

## MCP Tool Loading And Context Budget

Large MCP inventories can crowd the conversation context. When the host
provides tool search, deferred tool loading, namespaces, or searchable MCP
server descriptions, use that capability instead of loading every detailed tool
schema at startup.

Tool search reduces initial context pressure; it does not remove the need for
tool governance. Scholar AI tools must keep stable, searchable names; short
high-signal descriptions; bounded outputs; pagination or filters for large
results; and clear core entry points such as `literature.config_status`,
`literature.list_projects`, `literature.search_refs`,
`literature.evidence_pack_build`, `literature.evidence_integrity_gate`, and
the safe `source.*` inspection tools.

Do not answer context pressure by adding parallel tools for the same behavior.
Consolidate descriptions, split large result payloads, and keep
`agent_mcp_server/CAPABILITY_MAP.md` current so tool search and human operators
can find the right entry point without loading the whole toolbox.

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

1. Create rollback/audit records under the Git-ignored
   `docs/plans/_rollback/` directory.
2. Check official or mature references for the risky part of the operation.
3. Run commands from the repository root unless a command states otherwise.
4. For frontend/UI verification, launch `.\.venv-1\Scripts\python.exe .\start_desktop.py`
   and use the native `文献助手` window for final acceptance.
