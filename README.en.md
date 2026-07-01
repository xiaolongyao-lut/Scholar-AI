# Scholar AI

[中文](README.md) · [Full Documentation / Project Page](https://github.com/xiaolongyao-lut/Scholar-AI) · [Releases](https://github.com/xiaolongyao-lut/Scholar-AI/releases) · [Claude / Codex Toolbox](docs/claude-codex-toolbox.en.md) · [AI Agent Guide](docs/ai-agent-guide.md) · [Research Workflows and Skills](https://github.com/xiaolongyao-lut/scholar-ai-research-toolkit) · [Quick Start](#quick-start)

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

When running from source, the default entry point is the desktop app, not a standalone Vite browser page. A user can launch it manually from a terminal; Claude, Codex, or another coding agent should also start the same source desktop window in a visible terminal when validating frontend or interaction work. Browser-only checks are diagnostics, not final desktop acceptance.

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

`start_desktop.py` starts the FastAPI backend thread and the pywebview desktop window in the same Python process. A healthy launch opens a desktop window titled `文献助手`; the backend health endpoint is `http://127.0.0.1:8000/health`. Closing the window exits the source desktop process.

### OCR Configuration

OCR is used for scanned PDFs and image-only pages. In the desktop app, open **Settings → API Configuration → OCR Settings**.
Remote OCR secrets are managed under **API Credentials → OCR / Document Parsing**. The OCR settings card chooses local engines, applies saved OCR credentials, and stores the runtime policy.

`Automatically choose an available engine` is not a separate script and does not have its own path field. The backend tries available engines in this order:

```text
paddleocr_gpu -> rapidocr -> windows -> remote_api
```

To set a Python or PowerShell path, first choose a concrete engine in **Engine**, then fill that engine's options:

| Engine | Use case | Desktop setting |
|---|---|---|
| RapidOCR | Local CPU OCR for common scanned pages | Choose `RapidOCR`. Leave external Python empty to use the active runtime, or enter a `python.exe` that has `rapidocr` or `rapidocr_onnxruntime` installed. |
| Windows OCR | Built-in Windows OCR | Choose `Windows OCR`. Usually no path is needed; set `powershell.exe` only if the system cannot find it. |
| PaddleOCR GPU | Prepared PaddleOCR / GPU runtime | Choose `PaddleOCR GPU`. Enter the external Python that has `paddleocr` and `paddle`; set `predict`, `ocr`, or `__call__` only when the installed runtime needs it. |
| Remote API OCR | Existing external OCR service | First create a credential under **API Credentials → OCR / Document Parsing**, then choose `Remote API OCR` in OCR Settings and apply that credential. Enable upload consent only when page-image upload is acceptable. |

After saving, click **Check current engine**. The local runtime config is written to `workspace_artifacts/runtime_state/ocr_config.json` by default. These environment variables can override it:

| Environment variable | Purpose |
|---|---|
| `LITASSIST_OCR_POLICY` | `auto`, `engine`, or `none` |
| `LITASSIST_OCR_ENGINE` | Fixed engine name, such as `rapidocr`, `windows`, `paddleocr_gpu`, or `remote_api` |
| `LITASSIST_OCR_LANG` | OCR language tag, such as `en`, `zh`, or `zh-CN` |
| `LITASSIST_OCR_CONFIG_PATH` | OCR runtime config file path |
| `LITASSIST_RAPIDOCR_PYTHON` | External Python path for RapidOCR |
| `LITASSIST_PADDLEOCR_PYTHON` | External Python path for PaddleOCR |

If a user downloads another OCR program, the settings page does not scan the disk and list it automatically. To make it visible in the UI, use one of these integration paths:

| Integration path | What the UI shows |
|---|---|
| Expose it as Remote API OCR | An `OCR / Document Parsing` API credential, then a remote OCR runtime entry showing provider, model/parse mode, endpoint path, and upload consent. |
| Register a new backend OCR engine | A new OCR engine whose backend status includes name, availability, dependency state, and path fields. |

Built-in remote OCR credential presets:

| Service | Credential setup | OCR runtime behavior |
|---|---|---|
| Mistral OCR | Create an `OCR / Document Parsing` credential and choose the `Mistral OCR` preset. The default base URL is `https://api.mistral.ai/v1`; the default model is `mistral-ocr-latest`. | Usable as synchronous page-level OCR. The endpoint path is `/ocr`; `pages[].markdown` is merged into OCR text. |
| MinerU | Create an `OCR / Document Parsing` credential and choose the `MinerU Document Parsing` preset. The default base URL is `https://mineru.net/api`; parse mode can be `pipeline`, `vlm`, or `MinerU-HTML`. | MinerU is an asynchronous whole-document parsing flow, so it is not executed as automatic page-level OCR. The credential is kept for the document parser integration path. |

### Model Configuration

Chat / Q&A models, embedding, and rerank are configured in the desktop app under **Settings → API Configuration** or **Settings → Semantic Routing**. The settings page shows saved backend service configuration and backend-detected in-process local loading status; it does not scan every local model file.

| Type | Local deployment path | What the UI shows |
|---|---|---|
| Chat / Smart Reading model | Expose an OpenAI-compatible Chat API through Ollama, vLLM, LM Studio, or a custom service, such as local DeepSeek, Qwen, or Llama. | Enter provider, base URL, and model name in chat model settings. After saving, the UI shows that config and connection test results. Leave API key empty when the local service does not require one. |
| Embedding | Use a compatible embedding API service, or let the backend Python process load SentenceTransformer directly. | Compatible API shows the saved service URL and model name. In-process local loading shows backend-detected model name, device, weight cache directory, and environment-variable state. |
| Rerank | Use a compatible rerank API service, or let the backend Python process load a local rerank model directly. | Compatible API shows the saved service URL and model name. In-process local loading shows backend-detected model name, device, weight cache directory, max length, and environment-variable state. |

Common local chat service shape:

```text
Ollama / vLLM / LM Studio / custom OpenAI-compatible server
        -> base URL, for example http://127.0.0.1:11434/v1
        -> model, for example deepseek-r1, qwen2.5, or llama3
        -> API key, left empty when the local service does not require one
```

Local embedding in-process loading environment variables:

| Environment variable | Purpose |
|---|---|
| `LOCAL_EMBEDDING_MODEL_NAME` | Embedding model name for in-process local loading |
| `LOCAL_EMBEDDING_DEVICE` | Force `cpu`, `cuda`, or another device; leave empty for auto-detection |
| `LOCAL_EMBEDDING_ALLOW_DOWNLOAD` | Allow downloading missing weights |

Local rerank in-process loading environment variables:

| Environment variable | Purpose |
|---|---|
| `LOCAL_RERANK_MODEL_NAME` | Rerank model name for in-process local loading |
| `LOCAL_RERANK_DEVICE` | Force `cpu`, `cuda`, or another device; leave empty for auto-detection |
| `LOCAL_RERANK_ALLOW_DOWNLOAD` | Allow downloading missing weights |

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
