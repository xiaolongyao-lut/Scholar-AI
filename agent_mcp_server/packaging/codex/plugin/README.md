# Literature Assistant Toolbox Codex Plugin

Local Codex plugin bundle for the Literature Assistant MCP server.

## Manual Config Baseline

Copy `agent_mcp_server/packaging/codex/config.example.toml` into the MCP section of the Codex config you use, or add the server with the Codex MCP CLI:

```powershell
codex mcp add literature_assistant -- powershell -NoProfile -ExecutionPolicy Bypass -File C:\path\to\Scholar-AI\agent_mcp_server\bin\lit-assistant-mcp.ps1
```

For the current checkout, preview the fully resolved local command without mutating Codex config:

```powershell
.\agent_mcp_server\packaging\codex\add-user.ps1 -PrintOnly
```

## Local Plugin Install

Use this plugin directory from a local marketplace. The marketplace example in this folder points at the checked-out plugin path and does not contain credentials.

The plugin invokes the same wrapper used by the raw config path:

```powershell
C:\path\to\Scholar-AI\agent_mcp_server\bin\lit-assistant-mcp.ps1
```

## Backend URL

The default backend is `http://127.0.0.1:8000`. Override with:

```powershell
$env:LITERATURE_ASSISTANT_BASE_URL = "http://127.0.0.1:8000"
```

No provider keys are stored in this plugin.
