# Literature Assistant MCP Server

Local MCP toolbox for Codex and Claude.

## Scope

This project is source-checkout-first. It assumes the Literature Assistant repo
and `.venv-1` exist locally. Standalone installers, bundled exe builds, public
MCPB distribution, and dependency packaging are out of scope for the current
direction.

Claude/Codex should use this server to call Literature Assistant tools and to
inspect safe source code. If a capability is missing, add an MCP tool or backend
HTTP endpoint instead of creating an installer path.

## Tools

- `source.list_tree`
- `source.search`
- `source.read_file`
- `source.read_symbols`
- `literature.config_status`
- `literature.list_projects`
- `literature.list_materials`
- `literature.read_material`
- `literature.get_material_chunks`
- `literature.search_literature`
- `literature.ingest_then_search`
- `literature.export_annotations_markdown`

## Wrapper

```powershell
.\agent_mcp_server\bin\lit-assistant-mcp.ps1 -SelfTest
```

Normal MCP clients should run the wrapper without flags. It starts a stdio MCP
server and must not print extra protocol noise.

Optional non-secret runtime setting:

```powershell
$env:LITERATURE_ASSISTANT_BASE_URL = "http://127.0.0.1:8000"
$env:LITASSIST_MCP_ENABLE_EXPERIMENTAL_TOOLS = "1"
```

`LITASSIST_MCP_ENABLE_EXPERIMENTAL_TOOLS=1` enables OCR/page-image artifact
generation, visual review packs, translation packs, project packs, and the
bounded Python sandbox. Translation model calls still go through the Literature
Assistant backend; raw provider keys are never passed through MCP.

## Codex

Raw config baseline:

```powershell
Get-Content .\agent_mcp_server\packaging\codex\config.example.toml
```

Non-mutating CLI command preview:

```powershell
.\agent_mcp_server\packaging\codex\add-user.ps1 -PrintOnly
```

Local plugin bundle:

```text
agent_mcp_server/packaging/codex/plugin/
```

## Claude

Claude Desktop config example:

```text
agent_mcp_server/packaging/claude-desktop/claude_desktop_config.example.json
```

Optional local `.mcpb` shim for Claude Desktop testing only:

```powershell
.\agent_mcp_server\packaging\claude-desktop\build_mcpb.ps1
```

Non-mutating Claude Code command preview:

```powershell
.\agent_mcp_server\packaging\claude-code\add-user.ps1 -PrintOnly
```

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
