# Literature Assistant MCP Server

Local MCP toolbox for Codex and Claude.

## Scope

This project is source-checkout-first. It assumes the Literature Assistant repo
and `.venv-1` exist locally. Claude and Codex should connect to this server
through direct MCP config that points at the checked-out repository.

Claude/Codex should use this server to call Literature Assistant tools and to
inspect safe source code. If a capability is missing, add an MCP tool or backend
HTTP endpoint instead of creating an installer path.

## Tools

- `source.list_tree`
- `source.search`
- `source.read_file`
- `source.read_symbols`
- `source.inspect_routes`
- `source.find_references`
- `source.explain_entrypoints`
- `literature.config_status`
- `literature.list_projects`
- `literature.list_materials`
- `literature.read_material`
- `literature.get_material_chunks`
- `literature.search_refs`
- `literature.evidence_pack_build`
- `literature.project_scan_folder`
- `literature.figures_candidates`
- `literature.figures_generate`
- `literature.citations_sources`
- `literature.citations_detect_overlap`
- `literature.outline_generate`
- `literature.export_annotations_markdown`
- `literature.export_docx`
- `literature.journal_style_spec_draft`
- `literature.journal_style_spec_confirm`
- `literature.agent_bridge_status`
- `literature.agent_request_create`
- `literature.agent_request_list`
- `literature.agent_request_read`
- `literature.agent_resource_read`
- `literature.agent_progress`
- `literature.agent_result`
- `literature.agent_fail`

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
bounded Python sandbox. Translation model calls still go through the Literature
Assistant backend; raw provider keys are never passed through MCP.

By default, the wrapper attaches to `workspace_artifacts/runtime_state/desktop-runtime.json`.
If no healthy desktop runtime is present and the user has not deliberately
closed the app, it launches the source desktop app via `start_desktop.py` in a
visible terminal so the user can configure API/model/rerank/wiki settings in
the visible `文献助手` window and copy the printed
`LITERATURE_ASSISTANT_BASE_URL=http://127.0.0.1:<port>` line if an agent needs
manual help. After the user closes the desktop app, the wrapper does not
relaunch it automatically; start `start_desktop.py` manually or run
`.\agent_mcp_server\bin\lit-assistant-mcp.ps1 -ForceLaunch` for an explicit
Codex-driven reopen.

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
MCP-first path.

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
MCP-first path.

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
