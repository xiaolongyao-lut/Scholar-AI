# Scholar AI MCP Toolbox

Local MCP toolbox for Codex and Claude.

Related:

- Main project: <https://github.com/xiaolongyao-lut/Scholar-AI>
- Detailed toolbox guide: [docs/claude-codex-toolbox.md](../docs/claude-codex-toolbox.md)
- Research workflows and skill cards: <https://github.com/xiaolongyao-lut/scholar-ai-research-toolkit>

## Scope

This project is source-checkout-first. It assumes the Scholar AI repo and
`.venv-1` exist locally. Claude and Codex should connect to this server through
direct MCP config that points at the checked-out repository.

Claude/Codex should use this server to call Scholar AI tools and inspect safe
source code. If a capability is missing, add an MCP tool or backend HTTP
endpoint instead of creating an installer path.

## Tools

Use MCP `list_tools` for the live registry. For the public toolbox overview,
dependency notes, verification commands, and security boundary, read
[Claude / Codex Toolbox](../docs/claude-codex-toolbox.en.md). For the full scenario map,
typical workflow chains, full tool-name index, and the tool→code three-hop locator, read
[`CAPABILITY_MAP.md`](./CAPABILITY_MAP.md) — agents can pull it via
`source.read_file path=agent_mcp_server/CAPABILITY_MAP.md`.

Groups (prefix → implementation):

- `source.*` — read-only source inspection (`tools/source.py`):
  `list_tree`, `search`, `read_file`, `read_symbols`, `inspect_routes`,
  `find_references`, `explain_entrypoints`.
- `literature.*` — HTTP to the backend `literature_assistant/core`
  (`tools/runtime.py`): config/health (`config_status`, `health_check`,
  `zotero_attachment_health`), projects/materials (`list_projects`,
  `list_materials`, `read_material`, `get_material_chunks`,
  `project_scan_folder`), retrieval/evidence (`search_refs`,
  `evidence_pack_build`, `evidence_integrity_gate`, `knowledge_context_receipt`),
  knowledge/wiki/lexicon/scoring/product-docs/skill/source-vault families, OCR
  (`ocr_status`, `ocr_engines`, `ocr_health`, `ocr_execution_probe`,
  `ocr_material`), figures/citations/writing/export (`figures_candidates`,
  `figures_generate`, `citations_sources`, `citations_detect_overlap`,
  `outline_generate`, `academic_writing_lint`, `journal_style_spec_draft`,
  `journal_style_spec_confirm`, `export_annotations_markdown`, `export_docx`,
  `export_project_pack`, `translate_pack`, `prepare_visual_review`), agent
  bridge/collaboration (`agent_bridge_status`, `agent_workspace_status`,
  `agent_workspace_requirement`, `agent_request_create/list/read`,
  `agent_resource_read`, `agent_progress`, `agent_result`, `agent_fail`,
  `agent_handoff_card`, `single_paper_task_create`,
  `single_paper_completion_check`, `wiki_import`), workflow guardrails/replay
  (`workflow_passport`, `workflow_refresh_receipt`, `workflow_replay_lineage`,
  `workflow_replay_index`, `research_action_lifecycle`, `behavior_eval_pack`).
- `workflow.*` / `artifact.*` — JSON workflow engine and artifacts
  (`tools/workflow.py`): `workflow.create_plan`, `workflow.write_json_workflow`,
  `workflow.run_json_workflow`, `workflow.run_python_sandbox`,
  `artifact.write_markdown`, `artifact.read_artifact`, `artifact.list_artifacts`.

Experimental tools (OCR generation, visual review, translate/project packs,
Python sandbox) are gated by `LITASSIST_MCP_ENABLE_EXPERIMENTAL_TOOLS=1`.

## Proven Workflow Chains

These are the intended agent-facing chains. Use tool calls and returned refs as
the durable state, not pasted prose from model output. A reader-facing summary
of these chains is also published in [Claude / Codex Toolbox](../docs/claude-codex-toolbox.en.md).

| Chain | Tool order | Result |
|---|---|---|
| Evidence retrieval | `literature.list_projects` -> `literature.search_refs` -> `literature.evidence_pack_build` -> `literature.evidence_integrity_gate` | A source-grounded evidence pack with integrity status |
| Actual context loading | `literature.agent_resource_read` -> `literature.knowledge_context_receipt` -> provider tool-call transcript | Proof that a model received bounded Scholar AI context and returned the receipt hash |
| Paper reading | `literature.read_material` -> `literature.get_material_chunks` -> `literature.figures_candidates` -> `literature.agent_handoff_card` | A handoff-ready single-paper reading packet |
| Academic writing | `literature.evidence_pack_build` -> `literature.outline_generate` -> `literature.academic_writing_lint` -> `literature.export_docx` | A docx-ready writing path tied to evidence |
| OCR readiness | `literature.ocr_status` -> `literature.ocr_engines` -> `literature.ocr_health` -> `literature.ocr_material` | Engine selection, health blockers, then explicit OCR processing |
| Source repair | `source.search` -> `source.read_symbols` -> `source.read_file` -> `literature.agent_workspace_status` | Source understanding plus audit-aware repair context |
| Replay and handoff | `literature.workflow_passport` -> `literature.workflow_refresh_receipt` -> `literature.workflow_replay_lineage` -> `literature.agent_handoff_card` | Reproducible workflow lineage and a compact handoff card |

The live provider proof path uses real Scholar AI tool requests. It must not use
`Hi`, `ok`, or pure liveness prompts as evidence of model-context loading.
Provider credentials stay in process environment or the desktop credential
store and are never passed through this MCP server as raw values.

## Optional Full-Text Acquisition

Scholar AI processes PDFs and other local materials after they are inside a
project source folder. If an agent starts from a DOI, title, or publisher URL
and the PDF is not already local, use a separate full-text acquisition tool,
then put the resulting PDF under the user-confirmed project source folder and
call `literature.project_scan_folder`.

Recommended workflow:

```text
DOI/title/URL -> external full-text tool -> project source folder -> literature.project_scan_folder -> literature.search_refs or literature.evidence_pack_build
```

Keep acquisition tools separate from Scholar AI. They may support open-access
APIs, publisher links, or user-owned institutional access, but Scholar AI should
not embed publisher bypass logic or gray-source retrieval code.

Compliance boundary:

- Prefer open-access sources and user-authorized institutional access.
- Gray sources such as Sci-Hub or LibGen must be disabled by default in any
  external tool configuration, require explicit user opt-in, and remain the
  user's compliance responsibility.
- Do not pass institutional cookies, passwords, API keys, or absolute private
  source paths through this MCP toolbox.

Before implementing or changing any acquisition workflow, create a rollback
snapshot and recheck current mature references for MCP tool results, health
diagnostics, provider configuration, and the external acquisition tool's legal
and security boundary.

## Wrapper

```powershell
.\agent_mcp_server\bin\lit-assistant-mcp.ps1 -SelfTest
```

Normal MCP clients should run the wrapper without flags. It starts a stdio MCP
server and must not print extra protocol noise.

Optional non-secret runtime setting:

```powershell
$env:LITASSIST_MCP_ENABLE_EXPERIMENTAL_TOOLS = "1"
$env:LITASSIST_MCP_SKIP_BACKEND_AUTOSTART = "1"
$env:LITASSIST_MCP_BACKEND_STARTUP_TIMEOUT_SEC = "45"
```

`LITASSIST_MCP_ENABLE_EXPERIMENTAL_TOOLS=1` enables OCR/page-image artifact
generation, visual review packs, translation packs, project packs, and the
bounded Python sandbox. Translation model calls still go through the Scholar AI
backend; raw provider keys are never passed through MCP.

By default, the wrapper only attaches to an already healthy
`workspace_artifacts/runtime_state/desktop-runtime.json`. It does not open the
desktop app when no runtime is present. If the user asks the agent to start
`文献助手` or Scholar AI, the same MCP server should call
`literature.launch_desktop`; when no healthy desktop runtime is already
attached, this opens a visible PowerShell terminal and runs the source desktop
command from the repository root:

```powershell
& .\.venv-1\Scripts\python.exe .\start_desktop.py
```

The visible terminal is part of the explicit user-requested launch flow. The
stdio MCP wrapper itself stays hidden/protocol-clean. Closing stays a normal
user action: the user closes the `文献助手` window or its terminal, and ordinary
MCP reconnects will not reopen it silently.

Use `.\agent_mcp_server\bin\lit-assistant-mcp.ps1 -ForceLaunch` for an
explicit Codex-driven desktop reopen. Set
`LITASSIST_MCP_ALLOW_DESKTOP_AUTOSTART=1` only for a local workflow where MCP
startup is allowed to open the visible desktop app without another prompt.
When installing stdio MCP config on Windows, include `-WindowStyle Hidden` in
the PowerShell args so the MCP wrapper itself does not allocate a visible
terminal.

Headless Uvicorn autostart is debug-only. Set
`LITASSIST_MCP_ALLOW_HEADLESS_AUTOSTART=1` with a loopback
`LITERATURE_ASSISTANT_BASE_URL` to start
`literature_assistant.core.python_adapter_server:app` without the desktop UI.
Startup logs stay under `workspace_artifacts/runtime_state/mcp_backend/` so
stdio MCP output remains protocol-clean. Set
`LITASSIST_MCP_SKIP_BACKEND_AUTOSTART=1` to require an already-running runtime.

Debug-only headless example:

```powershell
$env:LITERATURE_ASSISTANT_BASE_URL = "http://127.0.0.1:<port>"
$env:LITASSIST_MCP_ALLOW_HEADLESS_AUTOSTART = "1"
```

## Codex

Raw config baseline:

```powershell
Get-Content .\agent_mcp_server\packaging\codex\config.example.toml
```

Non-mutating CLI command preview:

```powershell
.\agent_mcp_server\packaging\codex\add-user.ps1 -PrintOnly
```

Use the config example or the print-only helper above for the current
source-checkout path.

## Claude

Claude Desktop config example:

```text
agent_mcp_server/packaging/claude-desktop/claude_desktop_config.example.json
```

Non-mutating Claude Code command preview:

```powershell
.\agent_mcp_server\packaging\claude-code\add-user.ps1 -PrintOnly
```

Use the desktop config example or the Claude Code helper above for the current
source-checkout path.

## Security Foundation

- `PathPolicy`: path traversal prevention and allow/deny checks.
- `SecretRedactor`: multi-provider API key redaction.
- `safe_result`: unified tool output redaction and size limiting.
- `AuditLog`: JSONL audit trail under `workspace_artifacts/agent_mcp_workflows/.audit/`.
- `BackendClient`: HTTP client with timeouts and circuit breaker.

## Testing

```powershell
.\.venv-1\Scripts\python.exe -m pytest agent_mcp_server\tests -q
.\.venv-1\Scripts\python.exe -m compileall -q agent_mcp_server
```
