# Scholar AI Source-Boundary / Staging-Readiness Audit

Date: 2026-06-20

Mode: source-boundary and staging-readiness audit only. No staging, commit,
push, tag, release, restore, destructive cleanup, real-provider smoke, or
desktop smoke was performed.

## Actual Worktree

- `pwd`: `C:\Users\xiao\.codex\worktrees\63b2\Modular-Pipeline-Script`
- `git rev-parse --show-toplevel`:
  `C:/Users/xiao/.codex/worktrees/63b2/Modular-Pipeline-Script`
- Source project path from delegation:
  `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script`
- Current Git state: detached `HEAD (no branch)`, broadly dirty and unstaged.

Root-file note:

- `AI_WORKSPACE_GUIDE.md` and `AGENTS.md` were not present at this worktree
  root when read by relative path.
- They were read from the source project path:
  `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\AI_WORKSPACE_GUIDE.md`
  and
  `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\AGENTS.md`.

## Rollback Checkpoint

Checkpoint created before this audit file was written:

- ID: `20260620-191234-source-boundary-staging-readiness-20260620`
- Path:
  `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-dc2f0ccf5a1cbe02\20260620-191234-source-boundary-staging-readiness-20260620`
- Workspace:
  `C:\Users\xiao\.codex\worktrees\63b2\Modular-Pipeline-Script`

Restore command, only if the user explicitly requests rollback:

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\.codex\worktrees\63b2\Modular-Pipeline-Script" --checkpoint "20260620-191234-source-boundary-staging-readiness-20260620" --confirm-restore
```

## Files Read

Required files:

- `AI_WORKSPACE_GUIDE.md` from source project path.
- `AGENTS.md` from source project path.
- `SOURCE_RELEASE_POLICY.md`.
- `docs/plans/autonomous-execution-framework.md`.
- `docs/plans/autonomous-execution-planning-playbook.md`.
- `docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md`.
- `docs/plans/scholar-ai-reference-derived-code-plan-verification-audit-2026-06-20.md`.
- `docs/plans/longrun-goal-state-2026-06-19.json`.

Additional targeted reads:

- `.gitignore`.
- `tests/live_api_chat_full_writing_chain_smoke.py`.
- `tests/test_live_api_chat_full_writing_chain_smoke_harness.py`.
- Dirty status, diff name/status, diff stat, check-ignore output, scrub grep
  output, and JSON validation output.

## Mature / Official References Rechecked

- Git `gitignore` documentation:
  `https://git-scm.com/docs/gitignore`.
  Relevant rule: negated allowlist patterns only work when parent directories
  are also re-included; ignored files are intentionally untracked local files.
- Git `git add` documentation:
  `https://git-scm.com/docs/git-add`.
  Relevant rule: stage explicit pathspecs for the intended source boundary.
- GitHub release documentation:
  `https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases`.
  Relevant rule: releases include source archives for the selected tag.
- GitHub source archive documentation:
  `https://docs.github.com/en/repositories/working-with-files/using-files/downloading-source-code-archives`.
  Relevant rule: downloadable source archives are generated from the selected
  branch, tag, or commit tree.
- OWASP Secrets Management Cheat Sheet:
  `https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html`.
  Relevant rule: secrets should not enter source artifacts; release paths need
  pre-publication secret checks.
- GitHub secret scanning documentation:
  `https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning`.
  Relevant rule: secret scanning is a backstop, not a substitute for explicit
  source-boundary review.

## Current Dirty Inventory

Tracked modified paths from `git diff --name-status`:

- `.gitignore`.
- `agent_mcp_server/src/lit_assistant_mcp/tools/source.py`.
- `agent_mcp_server/tests/test_source_tools.py`.
- `frontend/openapi/modular-pipeline-openapi.json`.
- `frontend/src/components/chat/MessageRenderer.tsx`.
- `frontend/src/components/graph/DimensionGraphViewer.tsx`.
- `frontend/src/generated/openapi.ts`.
- `frontend/src/pages/AgentWorkspace.tsx`.
- `frontend/src/pages/Dialog.tsx`.
- `literature_assistant/core/discussion_task_store.py`.
- `literature_assistant/core/mcp_runtime/audit.py`.
- `literature_assistant/core/mcp_runtime/tool_result_formatter.py`.
- `literature_assistant/core/mcp_runtime/tool_use_runner.py`.
- `literature_assistant/core/models/__init__.py`.
- `literature_assistant/core/models/evidence.py`.
- `literature_assistant/core/models/runtime.py`.
- `literature_assistant/core/reranker_client.py`.
- `literature_assistant/core/routers/chat_mcp_integration.py`.
- `literature_assistant/core/routers/chat_router.py`.
- `literature_assistant/core/routers/credentials_router.py`.
- `literature_assistant/core/routers/evidence_router.py`.
- `literature_assistant/core/routers/local_literature_tool_bridge.py`.
- `literature_assistant/core/routers/model_config_router.py`.
- `literature_assistant/core/routers/resources_router/endpoints_materials_drafts.py`.
- `literature_assistant/core/routers/runtime_router.py`.
- `literature_assistant/core/routers/writing_router.py`.
- `literature_assistant/core/services/abstract_extractor.py`.
- `literature_assistant/core/services/smart_filter_engine.py`.
- `literature_assistant/core/wiki/export.py`.
- `literature_assistant/core/writing_runtime.py`.
- `packaging/pyinstaller/literature-assistant.spec`.
- `tests/test_env_example_contract.py`.
- `tests/test_evolution_release_hardening.py`.
- `tests/test_wiki_export.py`.
- `tests/test_wiki_permissions.py`.

Visible untracked paths from `git ls-files --others --exclude-standard`:

- `docs/plans/autonomous-execution-framework.md`.
- `docs/plans/autonomous-execution-planning-playbook.md`.
- `docs/plans/longrun-goal-state-2026-06-19.json`.
- `docs/plans/runbooks/longrun-local-supervisor.md`.
- `docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md`.
- `docs/plans/scholar-ai-reference-derived-code-plan-verification-audit-2026-06-20.md`.
- `frontend/src/components/chat/MessageRenderer.test.tsx`.
- `frontend/src/components/graph/DimensionGraphViewer.test.tsx`.
- `frontend/src/pages/AgentWorkspace.test.tsx`.
- `frontend/src/pages/Jobs.test.tsx`.
- `literature_assistant/core/provider_capabilities.py`.
- `tests/live_api_chat_full_writing_chain_smoke.py`.
- `tests/test_api_chat_local_literature_tool_use.py`.
- `tests/test_api_probe_semantics.py`.
- `tests/test_evidence_pack_build_contract.py`.
- `tests/test_live_api_chat_full_writing_chain_smoke_harness.py`.
- `tests/test_mcp_phase2_tool_loop.py`.
- `tests/test_runtime_router_contract.py`.
- `tests/test_writing_runtime_persistence.py`.
- `tests/test_writing_submission_export.py`.
- `tools/longrun/longrun-prompt.md`.
- `workspace_tests/evaluation_manifests/rerank_canary_dry_run_sample.json`.
- `workspace_tests/evaluation_manifests/rerank_canary_qrels.jsonl`.
- `workspace_tests/evaluation_manifests/rerank_canary_queries.jsonl`.
- `workspace_tests/fixtures/wiki_eval_smoke/manifest.json`.

Ignored/runtime note:

- `workspace_artifacts/runtime_state/provider-capabilities.json` is ignored by
  `.gitignore`; in this worktree the path was absent when checked. Prior
  source-project evidence says the runtime record had been cleaned to
  `{"records": {}}`; either state is local runtime state and must remain out
  of Git.

## Source-Boundary Classification

| Classification | Paths | Staging judgment |
|---|---|---|
| Public-source candidate: product/backend/frontend | `agent_mcp_server/src/lit_assistant_mcp/tools/source.py`, `literature_assistant/core/**` dirty files, `frontend/src/**` dirty product files, `frontend/openapi/modular-pipeline-openapi.json`, `frontend/src/generated/openapi.ts`, `packaging/pyinstaller/literature-assistant.spec`, `literature_assistant/core/provider_capabilities.py` | Candidate after explicit path staging and final scrub. These paths fall inside the policy allowlist for product code, typed API/client generation, and packaging reproducibility. |
| Public-source candidate: deterministic tests | Dirty tracked tests plus visible untracked tests under `tests/` and selected `frontend/**/*.test.tsx` | Candidate after explicit path staging and final secret/path scan. Current matches are expected fake-key/redaction fixtures, not real secrets. |
| Public-source candidate with run boundary | `tests/live_api_chat_full_writing_chain_smoke.py` and `tests/test_live_api_chat_full_writing_chain_smoke_harness.py` | Source file is path-safe and uses repo-relative runtime artifact paths, but execution reads configured runtime provider fields and may use real credentials. Stage only as a harness, not as proof that real-provider smoke was run. |
| Public-source candidate: selected fixtures | `workspace_tests/evaluation_manifests/rerank_canary_*.json*`, `workspace_tests/fixtures/wiki_eval_smoke/manifest.json` | Candidate only for selected manifest/fixture files. They are JSON/JSONL-valid and use relative `workspace_artifacts/...` output paths as sample output locations. Do not stage broader `workspace_tests/`. |
| Requires scrub / explicit publishing decision | `docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md`, `docs/plans/scholar-ai-reference-derived-code-plan-verification-audit-2026-06-20.md`, `docs/plans/longrun-goal-state-2026-06-19.json`, this audit file | Current audit evidence, but contains local absolute paths, checkpoint ids, downloaded-reference paths, worktree paths, and internal agent review history. Do not stage as public source unless the user explicitly accepts publishing internal evidence or a scrubbed public variant is created. |
| Local-only/private process docs | `docs/plans/autonomous-execution-framework.md`, `docs/plans/autonomous-execution-planning-playbook.md`, `docs/plans/runbooks/longrun-local-supervisor.md`, `tools/longrun/longrun-prompt.md` | Keep local-only by default. These are agent process/runbook files, include local absolute paths, and are outside the public product-source surface unless the user makes a separate policy decision. |
| Runtime/generated forbidden | `workspace_artifacts/`, `frontend/dist/`, runtime DB/log/profile/cache paths, provider capability runtime JSON | Never stage. `workspace_artifacts/` remains ignored and must stay out of Git. |
| Source release denylist | `.env*`, credential stores, local MCP runtime configs, `AI_WORKSPACE_GUIDE.md`, `AGENTS.md`, `.codex/`, `.claude/`, `.squad/`, `github/`, `workspace_references/` | Never stage for this release boundary. |
| Unknown ownership | None blocking this audit file. Product/test diffs remain broad and should be staged only after the parent thread accepts the full slice grouping. | No overwrite was performed. |

## `.gitignore` Allowlist Audit

Observed `.gitignore` change is path-explicit, not broad:

- Re-includes `docs/plans/` parent directories, then re-ignores the tree and
  re-includes named plan/audit/state/runbook files.
- Re-includes four frontend test files:
  `MessageRenderer.test.tsx`, `DimensionGraphViewer.test.tsx`,
  `AgentWorkspace.test.tsx`, and `Jobs.test.tsx`.
- Re-includes `tools/longrun/longrun-prompt.md` only, not the full `tools/`
  tree.
- Re-includes selected `workspace_tests` manifests/fixtures only, not broader
  diagnostics, scratch, benchmarks, provider proxy, or evaluation outputs.
- Re-includes selected backend tests and the source-safe live smoke harness
  files only.
- Keeps `/workspace_artifacts/` ignored.
- Keeps `.env` ignored; `git check-ignore -v -- .env` matched `.gitignore:6`.

Judgment:

- The allowlist mechanics are correct per Git `gitignore` parent-directory
  negation behavior.
- The public-source decision is stricter than the allowlist: allowlisted
  `docs/plans` and longrun files are visible for review but still require
  scrub/explicit decision before public staging.

## `docs/plans/` Boundary

Current audit evidence:

- `docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md`.
- `docs/plans/scholar-ai-reference-derived-code-plan-verification-audit-2026-06-20.md`.
- `docs/plans/longrun-goal-state-2026-06-19.json`.
- `docs/plans/scholar-ai-source-boundary-staging-readiness-2026-06-20.md`.

These files are useful for parent-thread staging review, but they are not clean
public-source docs:

- Scrub grep found `C:\Users\xiao\...` checkpoint/worktree/download paths.
- They contain internal audit history, delegated-worktree ids, and agent
  process records.
- The release policy denylist names internal plans and evidence under
  `docs/plans/` as local-only unless intentionally converted to public docs.

Local-only process docs:

- `docs/plans/autonomous-execution-framework.md`.
- `docs/plans/autonomous-execution-planning-playbook.md`.
- `docs/plans/runbooks/longrun-local-supervisor.md`.

`longrun-local-supervisor.md` contains many source-machine absolute commands
under `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script`; keep local-only
unless rewritten as a generic contributor document.

## Tests And Frontend Test Boundary

Candidate source-safe backend tests:

- `agent_mcp_server/tests/test_source_tools.py`.
- `tests/test_env_example_contract.py`.
- `tests/test_evolution_release_hardening.py`.
- `tests/test_wiki_export.py`.
- `tests/test_wiki_permissions.py`.
- `tests/test_api_chat_local_literature_tool_use.py`.
- `tests/test_api_probe_semantics.py`.
- `tests/test_evidence_pack_build_contract.py`.
- `tests/test_live_api_chat_full_writing_chain_smoke_harness.py`.
- `tests/test_mcp_phase2_tool_loop.py`.
- `tests/test_runtime_router_contract.py`.
- `tests/test_writing_runtime_persistence.py`.
- `tests/test_writing_submission_export.py`.

Candidate source-safe frontend tests:

- `frontend/src/components/chat/MessageRenderer.test.tsx`.
- `frontend/src/components/graph/DimensionGraphViewer.test.tsx`.
- `frontend/src/pages/AgentWorkspace.test.tsx`.
- `frontend/src/pages/Jobs.test.tsx`.

Notes:

- Scrub grep found expected fake fixture values such as `test-key`, `bad-key`,
  `Bearer test-key`, synthetic `sk-hidden`, and redaction test strings. These
  are not real credentials by inspection because they are deterministic test
  literals and are asserted to be masked/redacted.
- `tests/live_api_chat_full_writing_chain_smoke.py` is source-safe as code, but
  it resolves provider fields from runtime configuration during execution and
  writes temporary output under `workspace_artifacts/generated/output/...`.
  It must not be run as part of staging-readiness unless the parent thread
  explicitly authorizes real provider/API smoke.

## `tools/longrun/` And `workspace_tests/`

`tools/longrun/longrun-prompt.md`:

- Contains local policy instructions and references to `.env`, secrets, and
  `workspace_artifacts`.
- Classified local-only/private process material, despite path allowlist
  visibility.

`workspace_tests` selected files:

- JSON validation passed for:
  `workspace_tests/evaluation_manifests/rerank_canary_dry_run_sample.json`.
- JSONL validation passed for:
  `workspace_tests/evaluation_manifests/rerank_canary_queries.jsonl` with
  30 rows.
- JSONL validation passed for:
  `workspace_tests/evaluation_manifests/rerank_canary_qrels.jsonl` with
  40 rows.
- JSON validation passed for:
  `workspace_tests/fixtures/wiki_eval_smoke/manifest.json`.

Judgment:

- Selected manifests/fixtures are public-source candidates.
- Do not stage broader `workspace_tests/` directories; diagnostics, scratch,
  benchmarks, provider-proxy, and generated evaluation data remain local-only
  or generated.

## `tests/live_api_chat_full_writing_chain_smoke.py`

Judgment:

- Source-safe candidate, not runtime-safe to execute automatically.
- It computes `ROOT` from `tests/`, not from `C:\Users\xiao...`.
- It writes generated output under repo-relative `workspace_artifacts`.
- It masks the resolved API key in summaries.
- It reads configured provider fields and sets `CHAT_API_KEY` in-process for
  the smoke. That is acceptable for an explicitly authorized live smoke, but it
  is not safe to run as part of source-boundary staging audit.

Staging condition:

- Can be staged as a source harness if paired with the deterministic harness
  tests and clear documentation that real provider/API smoke remains unrun.
- Do not stage any output produced by running it.

## Explicit Staging Candidate Paths

These are candidates for explicit staging after parent approval and a final
pre-stage scan. They should be staged as explicit pathspecs, not via
`git add .`.

Product and generated API contract:

```text
.gitignore
agent_mcp_server/src/lit_assistant_mcp/tools/source.py
agent_mcp_server/tests/test_source_tools.py
frontend/openapi/modular-pipeline-openapi.json
frontend/src/components/chat/MessageRenderer.tsx
frontend/src/components/graph/DimensionGraphViewer.tsx
frontend/src/generated/openapi.ts
frontend/src/pages/AgentWorkspace.tsx
frontend/src/pages/Dialog.tsx
literature_assistant/core/discussion_task_store.py
literature_assistant/core/mcp_runtime/audit.py
literature_assistant/core/mcp_runtime/tool_result_formatter.py
literature_assistant/core/mcp_runtime/tool_use_runner.py
literature_assistant/core/models/__init__.py
literature_assistant/core/models/evidence.py
literature_assistant/core/models/runtime.py
literature_assistant/core/provider_capabilities.py
literature_assistant/core/reranker_client.py
literature_assistant/core/routers/chat_mcp_integration.py
literature_assistant/core/routers/chat_router.py
literature_assistant/core/routers/credentials_router.py
literature_assistant/core/routers/evidence_router.py
literature_assistant/core/routers/local_literature_tool_bridge.py
literature_assistant/core/routers/model_config_router.py
literature_assistant/core/routers/resources_router/endpoints_materials_drafts.py
literature_assistant/core/routers/runtime_router.py
literature_assistant/core/routers/writing_router.py
literature_assistant/core/services/abstract_extractor.py
literature_assistant/core/services/smart_filter_engine.py
literature_assistant/core/wiki/export.py
literature_assistant/core/writing_runtime.py
packaging/pyinstaller/literature-assistant.spec
```

Deterministic tests and source-safe live harness:

```text
tests/test_env_example_contract.py
tests/test_evolution_release_hardening.py
tests/test_wiki_export.py
tests/test_wiki_permissions.py
tests/live_api_chat_full_writing_chain_smoke.py
tests/test_api_chat_local_literature_tool_use.py
tests/test_api_probe_semantics.py
tests/test_evidence_pack_build_contract.py
tests/test_live_api_chat_full_writing_chain_smoke_harness.py
tests/test_mcp_phase2_tool_loop.py
tests/test_runtime_router_contract.py
tests/test_writing_runtime_persistence.py
tests/test_writing_submission_export.py
frontend/src/components/chat/MessageRenderer.test.tsx
frontend/src/components/graph/DimensionGraphViewer.test.tsx
frontend/src/pages/AgentWorkspace.test.tsx
frontend/src/pages/Jobs.test.tsx
```

Selected workspace test fixtures:

```text
workspace_tests/evaluation_manifests/rerank_canary_dry_run_sample.json
workspace_tests/evaluation_manifests/rerank_canary_qrels.jsonl
workspace_tests/evaluation_manifests/rerank_canary_queries.jsonl
workspace_tests/fixtures/wiki_eval_smoke/manifest.json
```

Docs requiring explicit decision before staging:

```text
docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md
docs/plans/scholar-ai-reference-derived-code-plan-verification-audit-2026-06-20.md
docs/plans/longrun-goal-state-2026-06-19.json
docs/plans/scholar-ai-source-boundary-staging-readiness-2026-06-20.md
```

## Forbidden / Do-Not-Stage Paths

Never stage these in the parent thread's source-boundary pass:

```text
workspace_artifacts/
frontend/dist/
.env
.env.*
AGENTS.md
AI_WORKSPACE_GUIDE.md
.codex/
.claude/
.squad/
github/
workspace_references/
workspace_ai/
output/
.app-profile/
*.db
*.db-shm
*.db-wal
*.log
```

Keep local-only unless the user makes a separate publishing decision and the
files are scrubbed:

```text
docs/plans/autonomous-execution-framework.md
docs/plans/autonomous-execution-planning-playbook.md
docs/plans/runbooks/longrun-local-supervisor.md
tools/longrun/longrun-prompt.md
```

Do not stage generated live-smoke outputs:

```text
workspace_artifacts/generated/output/live_api_chat_full_writing_chain_smoke_workspace/
workspace_artifacts/generated/output/run_live_api_chat_full_writing_chain_smoke.py
workspace_artifacts/runtime_state/provider-capabilities.json
```

## Scrub / Validation Results

Commands and results:

- `git check-ignore -v -- <selected docs/plans, tools, workspace_tests, workspace_artifacts, .env>`
  confirmed selected allowlist files are visible while
  `workspace_artifacts/runtime_state/provider-capabilities.json` and `.env`
  remain ignored.
- `git check-ignore -v -- <selected tests and frontend tests>` confirmed the
  reviewed tests are visible through path-explicit allowlists.
- `rg -n "C:\\Users|xiao|/Users/" docs\plans tools\longrun workspace_tests ...`
  found local absolute paths in `docs/plans/*` and
  `docs/plans/runbooks/longrun-local-supervisor.md`; no local absolute-path
  hits in the selected tests/frontend tests/workspace_tests fixtures.
- Secret-pattern scrub over selected tests/docs found no high-confidence real
  credentials. Hits are fake fixtures or redaction assertions such as
  `test-key`, `bad-key`, `Bearer test-key`, `sk-hidden`, and synthetic
  `Authorization: Bearer ...` test strings.
- JSON validation passed for `docs/plans/longrun-goal-state-2026-06-19.json`
  and selected `workspace_tests` JSON/JSONL files.
- `git diff --check -- <candidate source/test paths>` passed with no
  whitespace errors.

## Parent Thread Minimal Command Sequence

Run from the actual worktree root. This sequence intentionally includes
rollback checkpoint, mature-reference review, explicit path staging, index
checks, ignored-tracked-file check, and a rollback restore command marked as
user-approval-only.

```powershell
cd C:\Users\xiao\.codex\worktrees\63b2\Modular-Pipeline-Script

git status --short --branch

py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\.codex\worktrees\63b2\Modular-Pipeline-Script" --label "pre-explicit-source-staging-20260620"

# Mature / official source-boundary references to recheck before staging:
# - https://git-scm.com/docs/gitignore
# - https://git-scm.com/docs/git-add
# - https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases
# - https://docs.github.com/en/repositories/working-with-files/using-files/downloading-source-code-archives
# - https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html
# - https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning

rg -n "C:\\Users|xiao|/Users/|workspace_artifacts|\.env|api[_-]?key|Authorization|Bearer|token|secret|password" `
  .gitignore `
  agent_mcp_server/src/lit_assistant_mcp/tools/source.py `
  agent_mcp_server/tests/test_source_tools.py `
  frontend/src/components/chat/MessageRenderer.tsx `
  frontend/src/components/graph/DimensionGraphViewer.tsx `
  frontend/src/pages/AgentWorkspace.tsx `
  frontend/src/pages/Dialog.tsx `
  literature_assistant/core/provider_capabilities.py `
  literature_assistant/core/mcp_runtime/audit.py `
  literature_assistant/core/mcp_runtime/tool_result_formatter.py `
  literature_assistant/core/mcp_runtime/tool_use_runner.py `
  literature_assistant/core/routers/chat_router.py `
  literature_assistant/core/routers/credentials_router.py `
  literature_assistant/core/routers/model_config_router.py `
  tests/live_api_chat_full_writing_chain_smoke.py `
  tests/test_api_chat_local_literature_tool_use.py `
  tests/test_api_probe_semantics.py `
  tests/test_mcp_phase2_tool_loop.py `
  frontend/src/pages/Jobs.test.tsx `
  workspace_tests/evaluation_manifests `
  workspace_tests/fixtures/wiki_eval_smoke/manifest.json

git add -- `
  .gitignore `
  agent_mcp_server/src/lit_assistant_mcp/tools/source.py `
  agent_mcp_server/tests/test_source_tools.py `
  frontend/openapi/modular-pipeline-openapi.json `
  frontend/src/components/chat/MessageRenderer.tsx `
  frontend/src/components/graph/DimensionGraphViewer.tsx `
  frontend/src/generated/openapi.ts `
  frontend/src/pages/AgentWorkspace.tsx `
  frontend/src/pages/Dialog.tsx `
  literature_assistant/core/discussion_task_store.py `
  literature_assistant/core/mcp_runtime/audit.py `
  literature_assistant/core/mcp_runtime/tool_result_formatter.py `
  literature_assistant/core/mcp_runtime/tool_use_runner.py `
  literature_assistant/core/models/__init__.py `
  literature_assistant/core/models/evidence.py `
  literature_assistant/core/models/runtime.py `
  literature_assistant/core/provider_capabilities.py `
  literature_assistant/core/reranker_client.py `
  literature_assistant/core/routers/chat_mcp_integration.py `
  literature_assistant/core/routers/chat_router.py `
  literature_assistant/core/routers/credentials_router.py `
  literature_assistant/core/routers/evidence_router.py `
  literature_assistant/core/routers/local_literature_tool_bridge.py `
  literature_assistant/core/routers/model_config_router.py `
  literature_assistant/core/routers/resources_router/endpoints_materials_drafts.py `
  literature_assistant/core/routers/runtime_router.py `
  literature_assistant/core/routers/writing_router.py `
  literature_assistant/core/services/abstract_extractor.py `
  literature_assistant/core/services/smart_filter_engine.py `
  literature_assistant/core/wiki/export.py `
  literature_assistant/core/writing_runtime.py `
  packaging/pyinstaller/literature-assistant.spec `
  tests/test_env_example_contract.py `
  tests/test_evolution_release_hardening.py `
  tests/test_wiki_export.py `
  tests/test_wiki_permissions.py `
  tests/live_api_chat_full_writing_chain_smoke.py `
  tests/test_api_chat_local_literature_tool_use.py `
  tests/test_api_probe_semantics.py `
  tests/test_evidence_pack_build_contract.py `
  tests/test_live_api_chat_full_writing_chain_smoke_harness.py `
  tests/test_mcp_phase2_tool_loop.py `
  tests/test_runtime_router_contract.py `
  tests/test_writing_runtime_persistence.py `
  tests/test_writing_submission_export.py `
  frontend/src/components/chat/MessageRenderer.test.tsx `
  frontend/src/components/graph/DimensionGraphViewer.test.tsx `
  frontend/src/pages/AgentWorkspace.test.tsx `
  frontend/src/pages/Jobs.test.tsx `
  workspace_tests/evaluation_manifests/rerank_canary_dry_run_sample.json `
  workspace_tests/evaluation_manifests/rerank_canary_qrels.jsonl `
  workspace_tests/evaluation_manifests/rerank_canary_queries.jsonl `
  workspace_tests/fixtures/wiki_eval_smoke/manifest.json

git diff --cached --check

git ls-files -ci --exclude-standard

git diff --cached --name-status

# User-approval-only rollback restore. Do not run unless the user explicitly asks to roll back.
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\.codex\worktrees\63b2\Modular-Pipeline-Script" --checkpoint "<checkpoint-id-from-pre-explicit-source-staging-20260620>" --confirm-restore
```

Docs/plans staging, if and only if the parent thread intentionally decides to
publish internal evidence after accepting the absolute-path/internal-history
risk or after creating scrubbed variants:

```powershell
git add -- `
  docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md `
  docs/plans/scholar-ai-reference-derived-code-plan-verification-audit-2026-06-20.md `
  docs/plans/longrun-goal-state-2026-06-19.json `
  docs/plans/scholar-ai-source-boundary-staging-readiness-2026-06-20.md
```

## Parent Decisions Needed

1. Decide whether the public source archive should include internal
   `docs/plans` evidence. Policy default says no; current audit visibility
   allowlist says review is possible, not that publishing is safe.
2. Decide whether `tools/longrun/longrun-prompt.md` and
   `docs/plans/runbooks/longrun-local-supervisor.md` are purely local agent
   operations or should be rewritten as public contributor documentation.
3. Decide whether the source-safe live provider smoke harness belongs in the
   public test tree while real provider/API smoke remains unrun.
4. Decide whether selected `workspace_tests` fixtures are useful public
   reproducibility assets or should stay local-only despite being path-safe.

## Residual Risks

- This audit did not rerun backend/frontend suites; it relies on recorded
  evidence that backend passed `4175 passed, 52 skipped, 1 xfailed`, frontend
  passed `804 tests`, and build passed.
- Desktop pywebview smoke remains unrun.
- Real provider/API smoke remains unrun.
- Product/test dirty diffs are broad and still need explicit parent-thread
  grouping before staging.
- Public staging of `docs/plans` would expose local paths and internal agent
  evidence unless scrubbed or explicitly accepted.
- `workspace_artifacts/` must remain ignored and excluded from Git even though
  some source harnesses refer to it as a runtime output destination.

## Parent Current-Root Candidate Consistency Follow-Up, 2026-06-20

The seventh-round adversarial review noted that this audit was produced in a
detached worktree and did not prove that `63b2` candidate file contents matched
the current source project root before staging.

Parent follow-up result:

- `C:\Users\xiao\.codex\worktrees\63b2\Modular-Pipeline-Script` no longer
  exists, so equality against that worktree cannot be verified.
- The parent thread extracted the exact 53 explicit candidate paths from this
  record and checked them in the current source root:
  `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script`.
- All 53 candidate paths exist in the current source root and were SHA-256
  hashed.
- Runtime summary:
  `workspace_artifacts/generated/output/staging_candidate_current_root_consistency_summary.json`
  remains ignored.

Updated staging judgment:

```text
blocked_old_63b2_missing_current_root_candidates_hashed
```

Do not stage from, or compare against, the deleted `63b2` worktree. Any future
staging pass must run from the current source root, create a fresh rollback
checkpoint, repeat final scrub/diff checks, and use explicit pathspecs only
after user authorization.
