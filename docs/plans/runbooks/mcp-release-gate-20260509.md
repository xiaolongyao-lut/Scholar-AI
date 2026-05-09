# MCP Integration — Release Gate Snapshot (Phase 6)

Captured: 2026-05-09 UTC.

This is the release-gate evidence package for the MCP integration line
(plan: `docs/plans/active/2026-05-08-mcp-integration-plan.md` v0.3).

## TASK-601 — OpenAPI snapshot

```
OPENAPI_SHA_AFTER_SLICE_MCP = 30c115a681f3df110b8f5f45d730dc2798e09b1129928e08b490aaed2f4f45e6
total_paths = 144  (was 139 at end of Slice D; +5)
```

Added paths (all under `/api/mcp/*`):

| Method | Path |
| --- | --- |
| GET | `/api/mcp/audit` |
| GET, POST | `/api/mcp/servers` |
| GET, PUT, DELETE | `/api/mcp/servers/{server_id}` |
| POST | `/api/mcp/servers/{server_id}/test` |
| GET | `/api/mcp/servers/{server_id}/tools` |

Reproduce:

```bash
.venv-1/Scripts/python.exe scripts/export_openapi_schema.py \
    --output workspace_artifacts/openapi-after-mcp.json
python -c "import hashlib; print(hashlib.sha256(open('workspace_artifacts/openapi-after-mcp.json','rb').read()).hexdigest())"
```

## TASK-602 — Forbidden-path scan

`scripts/release_forbidden_path_scan.py` now rejects:

- `runtime_mcp_servers.json` (Phase 1A registry file with raw env values)
- any path containing `mcp_servers/` (audit log + per-server workdirs)

The runtime path layout is `runtime_state_path("mcp_servers", ...)`.
`runtime_state/**` is already gitignored and excluded from the
PyInstaller manifest by the existing forbidden-path rules; the new
rules add belt-and-braces coverage in case `runtime_state` is ever
relocated.

## TASK-603 — Secret scan

`detect-secrets scan` returns clean across every file touched in the
six MCP slices. Re-verified per-slice before each push:

- Phase 1B: `mcp_runtime/{server_store, security_policy, client_manager,
  tool_catalog}.py`, `routers/mcp_router.py`, `tests/test_mcp_phase1b_*.py`
- Phase 2: `mcp_runtime/{provider_tool_adapter, tool_result_formatter,
  tool_dispatcher, tool_use_runner}.py`, `routers/chat_mcp_integration.py`,
  `routers/chat_router.py`, `tests/test_mcp_phase2_*.py`
- Phase 3: `frontend/src/services/mcpApi*.ts`,
  `frontend/src/components/settings/McpServersSection.tsx`,
  `frontend/src/pages/Settings.tsx`
- Phase 4: `models/discussion.py`, `routers/discussion_advanced_router.py`,
  `tests/test_mcp_phase4_*.py`
- Phase 5: `mcp_runtime/audit.py`, `mcp_runtime/security_policy.py`,
  `mcp_runtime/tool_dispatcher.py`, `routers/mcp_router.py`,
  `tests/test_mcp_phase5_*.py`

Test fixtures use the `# pragma: allowlist secret` inline marker to
suppress the keyword detector on intentionally fake values
(`test-bearer-1234`, `test-serpapi-key-...`, `sk-test-...`). No
`.secrets.baseline` was created — that file is forbidden by R1.

## TASK-604 — Packaging note

The `mcp` and `fastmcp` SDKs are imported lazily inside
`mcp_runtime/client_manager.py`'s `_session_for` async context manager:

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
```

Other MCP modules use the local Pydantic models (`models.mcp.*`) and
never touch the third-party SDK at module load. Consequences:

1. App startup does NOT depend on `mcp` / `fastmcp` being installed —
   the registry CRUD endpoints work standalone.
2. PyInstaller does NOT bundle `mcp` / `fastmcp` automatically. Phase 0
   fixture (`tests/fixtures/mcp/echo_math_server.py`) is a dev-only test
   scaffold and is also unbundled.
3. Production users wanting to invoke MCP tools must:
   - install `mcp>=1.27.0,<2` and `fastmcp>=3.2.0,<4` into the same env
     as the literature_assistant backend, OR
   - rely on stdio servers whose own command provides the SDK
     (e.g. `npx @modelcontextprotocol/server-...` invocations).

If a future release artifact needs MCP bundled, add to
`scripts/build_windows_exe.ps1`:

```
--collect-all mcp --collect-all fastmcp
```

…and verify the forbidden-path scan after rebuild.

## Test surface

| Suite | Cases |
| --- | --- |
| `tests/test_chat_response_parser.py` (P0 hotfix) | 12 |
| `tests/test_mcp_server_store.py` (Phase 1A) | 22 |
| `tests/test_mcp_phase1b_integration.py` | 18 |
| `tests/test_mcp_phase2_tool_loop.py` | 27 |
| `tests/test_mcp_phase4_discussion.py` | 8 |
| `tests/test_mcp_phase5_hardening.py` | 17 |
| **Total** | **104** |

All green at the time of capture.

## Feature flags (env)

| Flag | Default | Effect when on |
| --- | --- | --- |
| `LITERATURE_ENABLE_MCP_TOOLS` | off | chat_ask delegates to McpToolUseRunner when request supplies `mcp_server_ids`; same gate for discussion `mcp_overrides`. |
| `LITERATURE_ENABLE_MCP_STREAMABLE_HTTP` | off | client_manager will open streamable_http sessions; otherwise raises McpStreamableHttpDisabledError. |
| `LITERATURE_MCP_HTTP_ALLOW_PRIVATE` | off | URL guard accepts private/loopback hosts for streamable_http. |
| `LITERATURE_MCP_RELAX_CAPS` | off | RunCaps skip the 2× clamp (caller may set MCP_MAX_TOOL_ROUNDS / MCP_MAX_TOTAL_TOOL_SECONDS / MCP_MAX_PARALLEL_TOOLS / MCP_TOOL_CALL_TIMEOUT_SECONDS without ceiling). |
| `MCP_AUDIT_MAX_LINES` | 5000 | Audit JSONL rotation threshold. |

Production default state: all flags off → MCP server registry + UI
present and inert. No tool execution path is reachable until the user
opts in.
