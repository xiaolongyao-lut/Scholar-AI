# Project File Organization Map

## Purpose

This file is the single entry point for where to place and find files in this repository.

## Root Directory (Keep Clean)

Only keep active runtime and evergreen docs in root:

- Active code entrypoints (`*.py`) and core packages (`layers/`, `routers/`, `models/`, `modules/`, `repositories/`)
- Active config (`pyproject.toml`, `pytest.ini`, `config/`)
- Evergreen docs:
  - `README.md`
  - `GETTING_STARTED.md`
  - `DEVELOPER_GUIDE.md`
  - `ARCHITECTURE.md`
  - `NAMING_AND_ARCHIVE_POLICY.md`
  - active design docs such as `FOCUS_REGISTRY_DESIGN.md`

## Historical Documentation

Use `docs/history/` by type:

- `docs/history/plans/` for execution plans and phase plans
- `docs/history/reports/` for one-off reports and status summaries
- `docs/history/diagnostics/` for logs and troubleshooting outputs
- `docs/history/sessions/` for session summaries
- `docs/history/phase/` for phase prompts and phase completion files
- `docs/history/harness/` for harness-specific archives

## Metrics and Evaluation Artifacts

Use `artifacts/metrics/history/` for historical evaluation JSON outputs:

- `BASELINE_METRICS_*.json`
- `eval_results*.json`
- estimate or experiment snapshots

Keep only the current baseline at root when needed by default scripts:

- `BASELINE_METRICS.json`

## Request Samples and One-Off JSON Inputs

Use `artifacts/requests/` for manual request payload samples:

- `req.json`
- `request.json`
- `test_request.json`

## Logs and Raw Diagnostics

Use `docs/history/diagnostics/root-archive/` for archived root logs and text dumps.

## Datasets

Keep active datasets and query sets at root only if scripts depend on root-relative paths:

- `eval_queries_v1.0.jsonl`
- `eval_queries_v2.0.jsonl`
- `eval_queries_v2.1.jsonl`
- `eval_queries_v2.1_canary30.jsonl`
- `gateb_goldset.jsonl`

## Rollback and Safety

Before any future file reorganization:

1. Create a snapshot under `.rollback_snapshots/<task>-<timestamp>/`
2. Move files by category
3. Run residual reference checks
4. Run smoke validation for impacted flows

## 2026-04-20 Reorganization (Executed)

Completed file consolidation:

- Root scattered plans moved to `docs/history/plans/root-archive/`
- Root scattered reports moved to `docs/history/reports/root-archive/`
- Root logs/text dumps moved to `docs/history/diagnostics/root-archive/`
- Historical metrics JSON moved to `artifacts/metrics/history/`
- Request sample JSON moved to `artifacts/requests/`

Rollback snapshot:

- `.rollback_snapshots/project-file-reorg-20260420-023843/`
