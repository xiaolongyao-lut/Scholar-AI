# Claude / Codex Toolbox

[中文](claude-codex-toolbox.md) · [Project README](../README.en.md) · [MCP server README](../agent_mcp_server/README.md)

Scholar AI provides a local MCP toolbox that lets Claude, Codex, and other MCP clients call local literature, evidence retrieval, writing export, OCR status, workflow artifacts, and safe source-inspection tools.

The toolbox turns local research material into callable tools. It does not hand raw API keys, runtime databases, logs, or private materials to external agents. Provider credentials remain managed by the Scholar AI backend or desktop settings.

## Use Cases

- Search local Scholar AI literature projects from Claude / Codex.
- Read page-level chunks, evidence packs, and bounded context.
- Use fixed chains for literature review, single-paper reading, writing export, OCR readiness, and workflow replay.
- Let code agents inspect allowlisted source files to understand interfaces and implementation.
- Review tool-call audits, artifacts, and handoff records through Agent Workspace.

## Connection Model

The MCP server lives under `agent_mcp_server/` and connects through stdio:

```text
Claude / Codex / MCP client
        |
        | stdio MCP
        v
agent_mcp_server/
        |
        | HTTP + local token
        v
Scholar AI backend
        |
        +-- literature workspace
        +-- chunk store and indexes
        +-- model and credential config
        +-- Agent Workspace audit artifacts
```

Self-test:

```powershell
.\agent_mcp_server\bin\lit-assistant-mcp.ps1 -SelfTest
```

Config preview:

```powershell
.\agent_mcp_server\packaging\codex\add-user.ps1 -PrintOnly
.\agent_mcp_server\packaging\claude-code\add-user.ps1 -PrintOnly
```

## Tool Groups

| Group | Representative Tools | Purpose |
|---|---|---|
| Source inspection | `source.list_tree`, `source.search`, `source.read_file`, `source.read_symbols`, `source.inspect_routes` | Inspect allowlisted source files, symbols, routes, and entry points. |
| Literature projects | `literature.list_projects`, `literature.list_materials`, `literature.read_material`, `literature.get_material_chunks` | Find projects, materials, metadata, and page-level chunks. |
| Evidence retrieval | `literature.search_refs`, `literature.evidence_pack_build`, `literature.evidence_integrity_gate`, `literature.knowledge_context_receipt` | Search refs, build evidence packs, check integrity, and create context receipts. |
| OCR and materials | `literature.ocr_status`, `literature.ocr_engines`, `literature.ocr_health`, `literature.ocr_material` | Check OCR policy, engine status, and authorized material processing paths. |
| Figures and citations | `literature.figures_candidates`, `literature.figures_generate`, `literature.citations_sources`, `literature.citations_detect_overlap` | Extract figure candidates, generate figure assets, and check citation sources or overlap. |
| Writing and export | `literature.outline_generate`, `literature.academic_writing_lint`, `literature.export_docx`, `literature.export_project_pack`, `literature.translate_pack` | Generate outlines, lint academic writing, and export Word/project/translation packs. |
| Agent Workspace | `literature.agent_workspace_status`, `literature.agent_resource_read`, `literature.agent_handoff_card`, `literature.workflow_passport` | Inspect audits, read resources, produce handoff cards, and replay workflow state. |
| Local workflows | `workflow.create_plan`, `workflow.run_json_workflow`, `artifact.write_markdown`, `artifact.read_artifact` | Write, read, and replay local JSON/Markdown workflow artifacts. |

The live registry returned by MCP `list_tools` is authoritative. See [agent_mcp_server/CAPABILITY_MAP.md](../agent_mcp_server/CAPABILITY_MAP.md) for the scenario map and tool-to-code locator.

## Proven Chains

| Chain | Tool Order | Output |
|---|---|---|
| Evidence retrieval | `literature.list_projects` -> `literature.search_refs` -> `literature.evidence_pack_build` -> `literature.evidence_integrity_gate` | Evidence pack with refs, pages, material provenance, and integrity status. |
| Actual context loading | `literature.agent_resource_read` -> `literature.knowledge_context_receipt` -> provider tool-call transcript | Proof that a model received bounded context and returned the receipt hash. |
| Single-paper reading | `literature.read_material` -> `literature.get_material_chunks` -> `literature.figures_candidates` -> `literature.agent_handoff_card` | Handoff-ready paper summary, figure candidates, and next actions. |
| Writing export | `literature.evidence_pack_build` -> `literature.outline_generate` -> `literature.academic_writing_lint` -> `literature.export_docx` | Word output tied to checked evidence. |
| OCR readiness | `literature.ocr_status` -> `literature.ocr_engines` -> `literature.ocr_health` -> `literature.ocr_material` | Engine readiness, health blockers, and authorized OCR processing. |
| Source repair | `source.search` -> `source.read_symbols` -> `source.read_file` -> `literature.agent_workspace_status` | Source understanding plus audit-aware repair context. |
| Workflow replay | `literature.workflow_passport` -> `literature.workflow_refresh_receipt` -> `literature.workflow_replay_lineage` | Replayable lineage for research actions, evidence, artifacts, and handoff. |

## Dependencies And Preconditions

| Item | Requirement |
|---|---|
| Scholar AI backend | Use `literature_assistant.core.python_adapter_server:app`. The desktop launcher starts the backend in the same process. |
| Python environment | Use the repository `.venv-1` environment when available. |
| MCP client | Claude, Codex, or another stdio MCP client. |
| Local literature workspace | Scholar AI projects and materials must be imported or scannable. |
| Models and credentials | Managed by the Scholar AI desktop app or backend settings; raw provider keys are not passed as MCP tool arguments. |
| Experimental tools | OCR/page-image generation, visual review, translation packs, project packs, and bounded Python sandbox require `LITASSIST_MCP_ENABLE_EXPERIMENTAL_TOOLS=1`. |

## Verification

Basic self-test:

```powershell
.\agent_mcp_server\bin\lit-assistant-mcp.ps1 -SelfTest
```

MCP server tests:

```powershell
.\.venv-1\Scripts\python.exe -m pytest agent_mcp_server\tests -q
```

Actual context-loading proof must not use `Hi`, `ok`, or pure liveness prompts. It requires real model tool requests for `literature.agent_resource_read` and `literature.knowledge_context_receipt`, plus receipt-hash backflow in the provider tool-call transcript.

## Security Boundary

- Source tools only read allowlisted paths.
- Tool outputs are redacted and size-limited before returning to MCP clients.
- Raw API keys, `.env`, runtime tokens, databases, logs, and local MCP client configs are outside the public read surface.
- Backend failures return structured errors, and repeated failures trigger a circuit breaker.
- Tool-call audits are written under `workspace_artifacts/agent_mcp_workflows/.audit/`.
- Full-text acquisition should remain separate from Scholar AI. Users are responsible for access rights, open-access checks, institutional access, and compliance.
