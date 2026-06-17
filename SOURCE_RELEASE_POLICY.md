# Public Source Release Policy

This repository publishes source from Git tags. GitHub release `Source code`
archives are generated from the tagged Git tree, so the public Git tree must be
the source boundary. Uploaded release assets may supplement that tree, but they
do not replace it.

## References Used

- GitHub Docs: release source archives are downloaded as `zip` or `tar.gz`
  from the selected tag or branch:
  https://docs.github.com/repositories/working-with-files/using-files/downloading-source-code-archives
- GitHub Docs: releases automatically include source archive links for the tag:
  https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases
- GitHub Docs and Git: `.gitignore` is for intentionally untracked local files:
  https://docs.github.com/en/get-started/git-basics/ignoring-files
- Open Source Guides: public projects should expose setup, contribution,
  license, and testing expectations:
  https://opensource.guide/starting-a-project/
- Mature project samples checked locally: `openhanako`, `open-webui`,
  `LightRAG`, `RAG-Anything`, `quivr-core`, `mempalace`, and `sa-rag`.

## Source Archive Goal

A release source archive should let a reviewer inspect, install dependencies,
run core tests, rebuild the app, and understand the release process without
including private state, generated runtime output, local agent instructions, or
credentials.

## Commit Allowlist

These paths are acceptable public Git candidates after normal review:

- Product code: `literature_assistant/`, `frontend/src/`,
  `frontend/index.html`, `frontend/openapi/`, `extension_packages/`.
- Frontend build metadata: `frontend/package.json`,
  `frontend/package-lock.json`, `frontend/tsconfig*.json`,
  `frontend/vite*.ts`, `frontend/postcss.config.js`,
  `frontend/eslint.config.js`.
- Backend and startup metadata: `pyproject.toml`, `requirements-ci.txt`,
  `requirements-pin.txt`, `run_literature_assistant.py`, `sitecustomize.py`,
  `start.py`, `start.bat`, `start_desktop.py`.
- Public project documents: `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `SECURITY.md`, `LICENSE`, `SOURCE_RELEASE_POLICY.md`, and selected
  user-facing how-to files under `docs/` after scrub review.
- Test reproducibility files: `pytest.ini`, `tests/`, selected
  `frontend/**/*.test.ts`, `frontend/**/*.test.tsx`, `frontend/tests/`,
  and `frontend/src/test/` when they contain no private fixtures.
- Release reproducibility files: `packaging/`, `.github/workflows/ci.yml`,
  `.github/workflows/online-smoke.yml`, and selected release workflows that do
  not require local-only secrets.
- Build and verification scripts that are safe to run from a clone:
  `scripts/audit_pyinstaller_hiddenimports.py`,
  `scripts/build_windows_exe.ps1`, `scripts/dump_pyinstaller_analysis.py`,
  `scripts/embedding_backfill.py`, `scripts/export_openapi_schema.py`,
  `scripts/ingest_project_pdfs.py`,
  `scripts/release_forbidden_path_scan.py`,
  `scripts/release_secret_scan.py`,
  `scripts/smoke_frozen_first_launch.py`, and
  `scripts/smoke_windows_release.ps1`.
- Example environment files: `.env.example` and `frontend.env.example` only
  when every value is a placeholder.

## Commit Denylist

Never commit these paths or file classes:

- Secrets and credentials: `.env`, `.env.*`, API keys, tokens, bearer headers,
  credential stores, local MCP server configs, and filled runtime config.
- Runtime state: `workspace_artifacts/`, `workspace_ai/`, `output/`,
  `.app-profile/`, browser profiles, SQLite/DB files, logs, caches, and release
  build outputs.
- Local agent and planning state: `AGENTS.md`, `AI_WORKSPACE_GUIDE.md`,
  `CLAUDE.md`, `GEMINI.md`, `MEMORY.md`, `OPEN_THREADS.md`, `.claude/`,
  `.codex/`, `.squad/`, `.kilo/`, `.cursor/`, `.continue/`, and `.opencode/`.
- Internal plans and evidence: `docs/plans/`, long-run runbooks, smoke
  artifacts, evaluation outputs, cost logs, and private review notes.
- External references and vendored workspaces: `github/`,
  `workspace_references/`, `legacy_archive/`, copied third-party repos, and
  non-installable skill/plugin catalogs.
- Dependency and build caches: `.venv-*`, `node_modules/`, `frontend/dist/`,
  `dist-runtime/`, `.pytest_cache/`, `.vite/`, `__pycache__/`, and compiled
  bytecode.
- Generated archives and installers unless they are uploaded as release assets,
  not committed to Git.

## Project Page Images

GitHub README images must resolve from a reachable URL. Do not upload UI
screenshots as release assets just to render the project page; release assets
should stay limited to the installer, checksum file, and approved release
evidence.

Preferred options:

1. Put stable, intentionally public screenshots under a Git-tracked docs path
   and reference them with relative Markdown paths.
2. If screenshots should not live in Git, upload them manually to a GitHub
   issue, discussion, or comment, then copy the generated
   `user-images.githubusercontent.com` / `github.com/user-attachments/assets`
   URL into the README.

There is no way for a public GitHub project page to show an image that is not
available from either the repository or another reachable hosted URL. If no
image host is approved, keep the README text-only.

## Pre-Push Checklist

Before pushing a source-boundary change:

1. Create a rollback snapshot for the files being edited.
2. Re-check official or mature references if the boundary changes.
3. Stage explicit paths only; do not use broad `git add .`.
4. Run `git diff --cached --check`.
5. Run `git ls-files -ci --exclude-standard` and fix any tracked ignored file.
6. Run the release secret scan over newly public paths.
7. Run the forbidden path scan for release trees or uploaded source assets.
8. Inspect the tagged tree before publishing a release archive.

## Release Rule

Changing GitHub's automatic `Source code (zip)` and
`Source code (tar.gz)` contents requires changing the Git tree referenced by the
release tag. Moving, deleting, or recreating release tags requires an explicit
release/history decision and a rollback branch or tag.
