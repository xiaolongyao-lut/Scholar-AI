# Changelog

## 0.1.5-alpha - 2026-05-19

Public source readiness line for the Scholar AI Workbench.

Highlights:

- MCP pending-call approval flow with backend suspend/resume, frontend approval modal, per-run remember behavior, timeout handling, and audit records.
- Evolution memory pipeline with candidate capture, review queue, promotion path, curator hooks, audit endpoint, and operator UI.
- Evolution visual regression baselines and E2E smoke coverage.
- Discussion evidence tracing and citation overlap helpers.
- Settings API cleanup and provider/model configuration hardening.
- Wiki, retrieval, rerank, and writing runtime path hardening around `literature_assistant/core/`.

Verification recorded locally:

- Frontend unit/integration: 424 tests passed.
- Frontend build: passed.
- Evolution Playwright E2E: 10/10 passed.
- Backend active suite: 2659 passed, 43 skipped, 1 xfailed.
