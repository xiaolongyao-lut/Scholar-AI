# Scholar AI

[中文](README.md) · [Research Workflows and Skills](https://github.com/xiaolongyao-lut/scholar-ai-research-toolkit) · [MCP Toolbox](agent_mcp_server/README.md) · [Quick Start](#quick-start)

Scholar AI is an open-source local research workspace for managing PDFs, building traceable evidence, drafting literature-review materials, and exposing a local research toolbox to Claude, Codex, and other MCP clients.

It is designed for students, researchers, and open-source experimenters who repeatedly read papers, collect source-grounded notes, export documents, and want AI agents to work with local research material without receiving raw provider credentials.

Current source version: [v0.1.8.4](CHANGELOG.md#0184---2026-06-17)

## What It Provides

- Local PDF projects, materials, page-level chunks, annotations, and reading state.
- Keyword, vector, rerank, and evidence-fusion retrieval over a local literature workspace.
- Source-grounded evidence packs with refs, pages, material provenance, and integrity checks.
- Smart reading, literature-review drafting, academic writing checks, figure candidates, and Word export.
- OCR readiness checks for scanned materials.
- A local MCP toolbox that lets Claude / Codex call Scholar AI tools without exposing raw API keys.
- Agent Workspace views for tool-call audit, workflow artifacts, handoff records, and replayable research actions.

## Related Repositories

| Repository | Contents |
|---|---|
| [Scholar AI](https://github.com/xiaolongyao-lut/Scholar-AI) | This repository: desktop app, backend, MCP toolbox, retrieval, writing, OCR, and tests. |
| [scholar-ai-research-toolkit](https://github.com/xiaolongyao-lut/scholar-ai-research-toolkit) | Scholar AI workflow recipes and skill cards for paper reading, translation, writing, OCR, experiment design, and evidence work. |

## Claude / Codex Toolbox

`agent_mcp_server/` provides a local MCP server. Claude, Codex, and other MCP clients can use it to call Scholar AI capabilities:

- Source inspection: `source.list_tree`, `source.search`, `source.read_file`, `source.read_symbols`, `source.inspect_routes`
- Literature projects: `literature.list_projects`, `literature.list_materials`, `literature.read_material`, `literature.get_material_chunks`
- Evidence retrieval: `literature.search_refs`, `literature.evidence_pack_build`, `literature.evidence_integrity_gate`, `literature.knowledge_context_receipt`
- OCR and material processing: `literature.ocr_status`, `literature.ocr_engines`, `literature.ocr_health`, `literature.ocr_material`
- Figures and citations: `literature.figures_candidates`, `literature.figures_generate`, `literature.citations_sources`, `literature.citations_detect_overlap`
- Writing and export: `literature.outline_generate`, `literature.academic_writing_lint`, `literature.export_docx`, `literature.export_project_pack`, `literature.translate_pack`
- Agent Workspace: `literature.agent_workspace_status`, `literature.agent_resource_read`, `literature.agent_handoff_card`, `literature.workflow_passport`
- Local workflow artifacts: `workflow.create_plan`, `workflow.run_json_workflow`, `artifact.write_markdown`, `artifact.read_artifact`

## Workflow Chains

| Chain | Tool Order | Output |
|---|---|---|
| Evidence retrieval | `literature.list_projects` -> `literature.search_refs` -> `literature.evidence_pack_build` -> `literature.evidence_integrity_gate` | Evidence pack with refs, pages, material provenance, and integrity status |
| Actual context loading | `literature.agent_resource_read` -> `literature.knowledge_context_receipt` -> provider tool-call transcript | Proof that a model received bounded context and a receipt hash |
| Single-paper reading | `literature.read_material` -> `literature.get_material_chunks` -> `literature.figures_candidates` -> `literature.agent_handoff_card` | Handoff-ready reading packet |
| Writing export | `literature.evidence_pack_build` -> `literature.outline_generate` -> `literature.academic_writing_lint` -> `literature.export_docx` | Word output tied to checked evidence |
| OCR readiness | `literature.ocr_status` -> `literature.ocr_engines` -> `literature.ocr_health` -> `literature.ocr_material` | Engine readiness, blockers, and authorized OCR processing |
| Workflow replay | `literature.workflow_passport` -> `literature.workflow_refresh_receipt` -> `literature.workflow_replay_lineage` | Replayable lineage for research actions, evidence, artifacts, and handoff |

## Quick Start

Requirements:

- Python 3.11
- Node.js 20+
- Windows PowerShell

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

MCP toolbox self-test:

```powershell
.\agent_mcp_server\bin\lit-assistant-mcp.ps1 -SelfTest
```

## Security Boundary

- Source tools only read allowlisted paths.
- Tool outputs are redacted and size-limited before returning to MCP clients.
- Raw provider keys, `.env` files, runtime tokens, databases, logs, and local MCP client configs are not part of the public read surface.
- Provider calls are configured through the Scholar AI backend or local desktop settings, not through raw MCP tool arguments.

## Repository Layout

| Path | Purpose |
|---|---|
| `agent_mcp_server/` | Local MCP toolbox for Claude / Codex |
| `literature_assistant/` | Python backend, retrieval, Wiki, writing, credentials, settings, and local APIs |
| `frontend/` | React / Vite / pywebview desktop console |
| `scripts/` | OpenAPI, index maintenance, release checks, and utility scripts |
| `tests/` | Backend, retrieval, security, MCP, and UI-adjacent regression tests |

## License

Scholar AI is released under the MIT License. Third-party components retain their own licenses.
