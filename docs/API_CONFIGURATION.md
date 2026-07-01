# API Configuration

Scholar AI keeps real API keys out of Git. Public files such as
`.env.example`, `frontend.env.example`, MCP manifests, and Skill manifests
only describe the variables or credential slots that users must fill locally.

## Where Secrets Live

- Local development: copy `.env.example` to `.env` and fill real backend keys.
- Frontend development: copy `frontend.env.example` to `frontend/.env.local`
  and fill only low-privilege frontend values.
- Desktop control console: add credentials in Settings, then bind them to MCP or
  Skill requirements through the local UI.
- Git: never commit `.env`, `frontend/.env.local`, raw API keys, bearer tokens,
  credential store files, or installed MCP runtime configs.

## Backend AI Providers

Use `.env.example` as the backend template.

Common fields are `ARK_API_KEY`, `ARK_BASE_URL`, `ARK_MODEL`,
`SILICONFLOW_API_KEY`, and `SILICONFLOW_RERANK_API_KEY`.

Example PowerShell setup:

```powershell
$env:ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
$env:ARK_MODEL = "ep-your-deployed-endpoint-id"
```

OpenAI-compatible gateways use `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and
`OPENAI_MODEL`. Put the actual key only in `.env` or the process environment.

Use provider-specific variables where available. They take precedence over
legacy generic variables.

## Frontend API Values

Use `frontend.env.example` as the frontend template and copy it to
`frontend/.env.local`.

Prefer routing the frontend to your local/backend API:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_FRONTEND_APP_TOKEN=
```

Only put low-privilege frontend keys in `frontend/.env.local`. Do not put
backend provider keys such as `OPENAI_API_KEY`, rerank keys, embedding keys, or
admin tokens in frontend env files.

## Desktop API Credentials

The desktop Settings page is the preferred place to configure runtime providers.
Open `Settings -> API Configuration -> API Credentials`, then create one saved
credential per provider/model pair. Each credential records:

- usage category: chat/writing, embedding, rerank, or OCR/document parsing;
- provider, base URL, model or parse mode;
- protocol shape, such as OpenAI-compatible chat, embeddings, rerank, or OCR;
- local trust confirmation for custom gateways or local model servers.

Chat, embedding, rerank, and OCR settings apply saved credentials by ID. Raw API
keys stay in the local credential store and are not returned to the frontend,
MCP server, or Git-tracked files.

For remote OCR:

- Mistral OCR uses the OCR credential category, base URL
  `https://api.mistral.ai/v1`, model `mistral-ocr-latest`, and endpoint path
  `/ocr`.
- MinerU uses the OCR/document parsing credential category, base URL
  `https://mineru.net/api`, and parse modes such as `pipeline`, `vlm`, or
  `MinerU-HTML`. It is an asynchronous whole-document parser, not a page-level
  OCR health probe.
- Custom OCR services can use the OCR protocol with their own base URL,
  endpoint path, model/parse mode, and explicit upload consent in OCR Settings.

## MCP Packages

This section is for optional MCP packages that Scholar AI can scan and manage
inside its own desktop control console. It is separate from the MCP-first
Claude/Codex toolbox under `agent_mcp_server/`.

Public MCP packages live under `extension_packages/mcp/`. A package root must
contain `literature-mcp.json` or `lit-mcp.json`.

MCP manifests should declare credential requirements, not secret values. Use
`required_credentials` to tell the local setup UI which environment variables
must be bound:

```json
{
  "id": "lit-mcp-image-gen",
  "name": "Image Generation MCP",
  "required_credentials": [
    {
      "id": "image_api_key",
      "label": "Image API key",
      "env": "IMAGE_API_KEY",
      "kind": "api_key",
      "provider_hints": ["openai-compatible-image"]
    }
  ]
}
```

When enabling a local MCP package:

1. Download or unpack the MCP package locally.
2. Open Settings -> MCP servers.
3. Choose the local package path.
4. Fill non-secret config fields in the wizard.
5. Bind each required env name, such as `IMAGE_API_KEY`, to a saved credential.
6. Probe and enable the server.

The installed runtime config should store `env_refs` that point to local
credential IDs. It should not store raw API keys in Git or in public manifests.

## Skill Packages

Public Skill packages live under `extension_packages/skills/`. A package root
must contain `SKILL.md`.

If a Skill needs an API key, declare it in the Skill frontmatter as a required
credential slot:

```yaml
---
name: image-helper
description: Generate or edit images through a configured provider.
required_credentials:
  - id: image_api_key
    label: Image API key
    env: IMAGE_API_KEY
    kind: api_key
    provider_hints:
      - openai-compatible-image
config_fields:
  - id: image_base_url
    label: Image API base URL
    type: text
    default: https://api.example.com/v1
---
```

The Skill should read the environment variable named by the credential slot at
runtime. The API key value is supplied locally by Scholar AI's credential
binding, not by the Git-tracked `SKILL.md`.

## Image Generation Example

For an image-generation MCP or Skill, use this local-only env shape:

```dotenv
IMAGE_API_KEY=your_image_provider_key_here
IMAGE_BASE_URL=https://api.example.com/v1
IMAGE_MODEL=your-image-model
```

Commit only the manifest or `SKILL.md` that declares `IMAGE_API_KEY` as a
required credential. Do not commit a filled `.env`, generated images, provider
tokens, or local runtime records.

## Before Publishing Config Changes

Run the release scans over the files you plan to publish:

```powershell
.\.venv-1\Scripts\python.exe scripts\release_secret_scan.py --input <staging-dir> --skip-detect-secrets
.\.venv-1\Scripts\python.exe scripts\release_forbidden_path_scan.py --mode onedir --input <staging-dir>
```

If a scan reports a real secret, rotate the key before publishing.
