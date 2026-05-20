# Security Policy

## Reporting

Report suspected vulnerabilities privately through GitHub Security Advisories or by contacting the project maintainer directly.

Please do not open a public issue for:

- Credential leakage.
- Unsafe file read/write behavior.
- MCP approval bypasses.
- Prompt-injection paths that can trigger external tool use.
- Cross-project data exposure.
- Provider key logging or Authorization header leakage.

## Supported Surface

Security reports are currently accepted for the active source branch and the `0.1.5-alpha` source readiness line.

## Secrets

Do not commit real `.env` files, provider API keys, browser profiles, SQLite runtime databases, model caches, or generated workspace output. Use `.env.example` and `.env.frontend.example` for documentation.

## Local-First Boundary

Scholar AI Workbench is designed to keep generated artifacts and runtime state local by default. External LLM, embedding, rerank, or MCP providers should be configured explicitly by the operator.
