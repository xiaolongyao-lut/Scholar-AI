# Scholar AI

[中文](README.md) · [Releases](https://github.com/xiaolongyao-lut/Scholar-AI/releases) · [Claude / Codex Toolbox](docs/claude-codex-toolbox.en.md) · [Research Workflows and Skills](https://github.com/xiaolongyao-lut/scholar-ai-research-toolkit) · [Quick Start](#quick-start)

Scholar AI is an open-source local research workspace for managing PDFs, building traceable evidence, drafting literature-review materials, and exposing a local research toolbox to Claude, Codex, and other MCP clients.

It is designed for students, researchers, and open-source experimenters who repeatedly read papers, collect source-grounded notes, export documents, and want AI agents to work with local research material without receiving raw provider credentials.

Current source version: [v0.1.8.4](CHANGELOG.md#0184---2026-06-17)

## What It Provides

- Local PDF projects, materials, page-level chunks, annotations, and reading state.
- Keyword, vector, rerank, and evidence-fusion retrieval over a local literature workspace.
- Source-grounded evidence packs with refs, pages, material provenance, and integrity checks.
- Smart reading, literature-review drafting, academic writing checks, figure candidates, and Word export.
- OCR readiness checks for scanned materials.
- A local [MCP toolbox](docs/claude-codex-toolbox.en.md) that lets Claude / Codex call Scholar AI tools without exposing raw API keys.
- Agent Workspace views for tool-call audit, workflow artifacts, handoff records, and replayable research actions.

## Related Repositories

| Repository | Contents |
|---|---|
| [Scholar AI](https://github.com/xiaolongyao-lut/Scholar-AI) | This repository: desktop app, backend, [MCP toolbox](docs/claude-codex-toolbox.en.md), retrieval, writing, OCR, and tests. |
| [scholar-ai-research-toolkit](https://github.com/xiaolongyao-lut/scholar-ai-research-toolkit) | Scholar AI workflow recipes and skill cards for paper reading, translation, writing, OCR, experiment design, and evidence work. |

## Claude / Codex Toolbox

[`agent_mcp_server/`](agent_mcp_server/README.md) provides a local MCP server so Claude, Codex, and other MCP clients can call Scholar AI literature retrieval, evidence-pack, OCR, writing-export, Agent Workspace, and safe source-inspection tools.

See [Claude / Codex Toolbox](docs/claude-codex-toolbox.en.md) for detailed tool groups, proven chains, dependencies, verification commands, and security boundaries.

## RAG And Evidence Architecture

Scholar AI is built around a local literature RAG and evidence pipeline. The project page shows the spine; see [RAG and Evidence Architecture](docs/rag-evidence-architecture.en.md) for module details, code entry points, and fallback boundaries.

```text
PDF / Markdown / OCR materials
        -> ingestion and structured chunks
        -> doc_store / chunk_store / embedding cache
        -> keyword + vector + rerank hybrid retrieval
        -> search_refs / evidence_pack_build / integrity gate
        -> smart reading / review writing / Word export / MCP tool calls
```

This pipeline turns "the system found something" into "this project, material, chunk, locator, and evidence status support this claim." Claude, Codex, and other MCP clients receive controlled tool results from this pipeline.

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

For tool groups, proven chains, dependencies, verification commands, and security boundaries, see [Claude / Codex Toolbox](docs/claude-codex-toolbox.en.md).

## Security Boundary

- Source tools only read allowlisted paths.
- Tool outputs are redacted and size-limited before returning to MCP clients.
- Raw provider keys, `.env` files, runtime tokens, databases, logs, and local MCP client configs are not part of the public read surface.
- Provider calls are configured through the Scholar AI backend or local desktop settings, not through raw MCP tool arguments.

## Repository Layout

| Path | Purpose |
|---|---|
| [`agent_mcp_server/`](agent_mcp_server/README.md) | Local [MCP toolbox](docs/claude-codex-toolbox.en.md) for Claude / Codex |
| `literature_assistant/` | Python backend, retrieval, Wiki, writing, credentials, settings, and local APIs |
| `frontend/` | React / Vite / pywebview desktop console |
| `scripts/` | OpenAPI, index maintenance, release checks, and utility scripts |
| `tests/` | Backend, retrieval, security, MCP, and UI-adjacent regression tests |

## License

Scholar AI is released under the MIT License. Third-party components retain their own licenses.
