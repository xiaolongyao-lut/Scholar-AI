# Scholar AI

[中文](README.md) · [Releases](https://github.com/xiaolongyao-lut/Scholar-AI/releases) · [Claude / Codex Toolbox](docs/claude-codex-toolbox.en.md) · [Research Workflows and Skills](https://github.com/xiaolongyao-lut/scholar-ai-research-toolkit) · [Quick Start](#quick-start)

Scholar AI is a local research workspace for PDF papers, page-level evidence, reading notes, Wiki knowledge, and literature-review writing. The desktop app manages materials, settings, and task views; the local MCP server lets Claude, Codex, or another MCP client call the same research workflow with user authorization.

This repository includes the desktop app, FastAPI backend, RAG / evidence pipeline, MCP toolbox, frontend UI, tests, and release scripts. It is intended for source checkouts, architecture inspection, reusable local research workflows, and continued development.

Published builds and historical versions are listed in [GitHub Releases](https://github.com/xiaolongyao-lut/Scholar-AI/releases).

## What It Provides

- Local PDF projects, materials, page-level chunks, annotations, and reading positions.
- Keyword, vector, rerank, and evidence-fusion retrieval over a local literature workspace.
- Source-grounded evidence packs with refs, pages, material provenance, and integrity checks.
- Smart reading, literature-review drafting, academic writing checks, figure candidates, and Word export.
- OCR readiness checks for scanned materials.
- A local [MCP toolbox](docs/claude-codex-toolbox.en.md) that lets Claude / Codex call Scholar AI tools without exposing raw API keys.
- A task center for long-running jobs, tool-call results, and replayable research artifacts.

## Related Repositories

| Repository | Contents |
|---|---|
| [Scholar AI](https://github.com/xiaolongyao-lut/Scholar-AI) | This repository: desktop app, backend, [MCP toolbox](docs/claude-codex-toolbox.en.md), retrieval, writing, OCR, and tests. |
| [scholar-ai-research-toolkit](https://github.com/xiaolongyao-lut/scholar-ai-research-toolkit) | Scholar AI workflow recipes and skill cards for paper reading, translation, writing, OCR, experiment design, and evidence work. |

## Claude / Codex Toolbox

[`agent_mcp_server/`](agent_mcp_server/README.md) provides a local MCP server for Claude, Codex, and other MCP clients. It exposes Scholar AI through controlled tool groups: `source.*`, `literature.*`, `workflow.*`, and `artifact.*`. The server calls the local backend with a local token and does not receive raw provider keys.

See [Claude / Codex Toolbox](docs/claude-codex-toolbox.en.md) for detailed tool groups, proven chains, dependencies, verification commands, and security boundaries.

## How It Works

```text
Claude / Codex / MCP client
        |
        | 1. stdio MCP: list_tools / call_tool
        v
agent_mcp_server/
        |
        +-- source.*       read-only source tree, symbols, routes, file excerpts
        +-- literature.*   backend literature, evidence, OCR, writing, knowledge APIs
        +-- workflow.*     local JSON workflow planning, execution, replay
        +-- artifact.*     Markdown / JSON artifact read-write index
        |
        | HTTP + local token
        v
Scholar AI backend
        |
        +-- FastAPI routers and typed response models
        +-- project / material / chunk stores
        +-- retrieval, evidence, OCR, writing, export services
        +-- model and credential settings
        +-- task, audit, and workflow artifacts
```

The desktop app owns the literature workspace, PDF reading, model settings, credential management, and task views. The MCP toolbox exposes local capabilities to user-authorized Claude / Codex clients: `source.*` reads allowlisted source files; `literature.*` calls backend literature APIs; `workflow.*` and `artifact.*` keep research actions and artifacts replayable. Tool results are redacted, size-limited, and returned with machine-readable refs, locators, and integrity state.

## RAG And Evidence Architecture

Scholar AI's retrieval pipeline uses project, material, page, and chunk identifiers as the base locator model. Ingestion writes doc, chunk, and page-locator records; retrieval, Wiki synthesis, smart reading, review writing, and MCP tool calls reuse those locators and record refs, locator coverage, and integrity state during evidence-pack construction. See [RAG and Evidence Architecture](docs/rag-evidence-architecture.en.md) for module details, code entry points, and fallback boundaries.

```text
PDF / Markdown / OCR materials
        |
        v
ingestion and structured chunks
        |  doc_store / chunk_store / page locator / section_path
        v
seed retrieval
        |  lexical refs / BM25 / dense embeddings / optional rerank
        v
bounded expansion
        |  TOLF aspect-query diffusion
        |  bridge-lexicon query expansion
        |  Wiki linked-page expansion
        |  project + wiki weighted RRF
        |  same-section table / formula / figure siblings
        v
evidence shaping
        |  search_refs / evidence_pack_build / locator coverage
        v
integrity gates
        |  evidence_integrity_gate / qrels status / context receipt
        v
smart reading / review writing / Word export / MCP tool calls
```

The output stage keeps the same evidence record: project, material, page, chunk, and integrity state. `search_refs` handles lightweight lookup; smart reading can add TOLF, RRF, structured neighbors, and hybrid retrieval; `evidence_pack_build` combines project chunks, Wiki refs, and knowledge refs into reviewable evidence packs. Claude, Codex, and other MCP clients read those controlled evidence results through MCP.

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
