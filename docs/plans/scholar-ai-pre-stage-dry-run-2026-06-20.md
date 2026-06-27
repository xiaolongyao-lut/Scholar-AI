# Scholar AI Pre-Stage Dry-Run Report

Date: 2026-06-20

Mode: pre-stage dry-run verification only. No `git add`, `git add -N`,
commit, push, tag, release, restore, destructive cleanup, real provider/API
smoke, or credential read/write was performed.

## Actual Worktree

- `pwd`: `C:\Users\xiao\.codex\worktrees\425d\Modular-Pipeline-Script`
- `git rev-parse --show-toplevel`:
  `C:/Users/xiao/.codex/worktrees/425d/Modular-Pipeline-Script`
- Source project path from delegation:
  `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script`
- Git state: detached `HEAD (no branch)`, broad unstaged dirty worktree.

Root-file note:

- `AI_WORKSPACE_GUIDE.md` and `AGENTS.md` were absent from this worktree root.
- Both were read from the source project path:
  `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\AI_WORKSPACE_GUIDE.md`
  and
  `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\AGENTS.md`.

Runtime note:

- This worktree has no `.venv-1`.
- Focused Python tests were executed from this worktree root using the source
  project virtual environment at
  `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe`.
- The current worktree has no `frontend/node_modules`. Source-project
  `frontend\node_modules` exists, but running its `vitest.cmd` from this
  worktree fails because `vite.config.ts` resolves `vitest` from this worktree
  directory. No dependency install, symlink, or mutation was performed.

## Rollback Checkpoint

Checkpoint created before writing this report:

- ID: `20260620-193944-pre-stage-dry-run-20260620`
- Path:
  `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-3b6126b2c2480ee6\20260620-193944-pre-stage-dry-run-20260620`
- Workspace:
  `C:\Users\xiao\.codex\worktrees\425d\Modular-Pipeline-Script`

Restore command, only if the user explicitly requests rollback:

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\.codex\worktrees\425d\Modular-Pipeline-Script" --checkpoint "20260620-193944-pre-stage-dry-run-20260620" --confirm-restore
```

## Required Files Read

- `AI_WORKSPACE_GUIDE.md` from source project path.
- `AGENTS.md` from source project path.
- `SOURCE_RELEASE_POLICY.md`.
- `docs/plans/autonomous-execution-framework.md`.
- `docs/plans/autonomous-execution-planning-playbook.md`.
- `docs/plans/scholar-ai-source-boundary-staging-readiness-2026-06-20.md`.
- `docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md`.
- `docs/plans/scholar-ai-reference-derived-code-plan-verification-audit-2026-06-20.md`.
- `docs/plans/longrun-goal-state-2026-06-19.json`.

## Mature / Official References Rechecked

- Git `gitignore` documentation:
  `https://git-scm.com/docs/gitignore`.
  Relevance: explicit negation rules require parent-directory re-inclusion;
  ignored local/private trees should not be broadly staged.
- Git `git add` documentation:
  `https://git-scm.com/docs/git-add`.
  Relevance: staging should use explicit pathspecs for the intended index
  update.
- GitHub releases documentation:
  `https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases`.
  Relevance: release source archives are attached to release/tag state.
- GitHub source archive documentation:
  `https://docs.github.com/en/repositories/working-with-files/using-files/downloading-source-code-archives`.
  Relevance: downloadable source archives come from a branch, tag, or commit
  tree.
- GitHub secret scanning documentation:
  `https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning`.
  Relevance: secret scanning is a backstop; source-boundary review must still
  prevent credentials from entering Git.
- OWASP Secrets Management Cheat Sheet:
  `https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html`.
  Relevance: secrets should not be embedded into source artifacts or release
  payloads.

## Dirty Worktree Ownership Audit

Public-source candidates:

- Product/runtime code:
  `.gitignore`,
  `agent_mcp_server/src/lit_assistant_mcp/tools/source.py`,
  `literature_assistant/core/**` dirty files,
  `literature_assistant/core/provider_capabilities.py`,
  `frontend/src/**` dirty product files,
  `frontend/openapi/modular-pipeline-openapi.json`,
  `frontend/src/generated/openapi.ts`,
  and `packaging/pyinstaller/literature-assistant.spec`.
- Deterministic tests and source-safe live harness:
  tracked dirty tests, selected untracked `tests/*.py`, and selected frontend
  `*.test.tsx` files named by the source-boundary audit.
- Selected workspace fixtures:
  `workspace_tests/evaluation_manifests/rerank_canary_*.json*` and
  `workspace_tests/fixtures/wiki_eval_smoke/manifest.json`.

Local-only/private or publishing-decision paths:

- `docs/plans/*` evidence records, including the prior source-boundary audit
  and this dry-run report.
- `docs/plans/autonomous-execution-framework.md`,
  `docs/plans/autonomous-execution-planning-playbook.md`,
  `docs/plans/runbooks/longrun-local-supervisor.md`,
  and `tools/longrun/longrun-prompt.md`.

Forbidden runtime/generated/private paths:

- `workspace_artifacts/`, `.env*`, credential/runtime stores, DB/log/profile
  output, root local agent files, `github/`, `workspace_references/`, and
  `frontend/dist/`.

Unknown ownership:

- None blocking this dry-run. The dirty worktree is broad, but the candidate
  set from `scholar-ai-source-boundary-staging-readiness-2026-06-20.md` remains
  separable by explicit pathspec.

## Explicit Candidate Path Verdict

Verdict: safe to proceed to parent-thread explicit path staging for the
candidate source/test/fixture paths, provided the parent thread stages only the
explicit path list and does not include local-only docs/plans evidence unless a
separate publishing decision is made.

Candidate path existence:

- 53 candidate paths checked.
- 0 missing paths.

Staging should include only:

- Product/backend/frontend/generated API/PyInstaller paths listed in
  `scholar-ai-source-boundary-staging-readiness-2026-06-20.md`.
- Deterministic backend/frontend tests and the source-safe live smoke harness
  listed there.
- Selected workspace JSON/JSONL fixtures listed there.

Staging should not include:

- `docs/plans/*` evidence records by default.
- `tools/longrun/longrun-prompt.md` or local runbooks by default.
- Any runtime/generated/private path.

## Forbidden Path Confirmation

`git check-ignore -v --` confirmed:

- `workspace_artifacts/runtime_state/provider-capabilities.json` remains
  ignored by `.gitignore:220:/workspace_artifacts/`.
- `.env` remains ignored by `.gitignore:6:.env`.
- `AGENTS.md` remains ignored by `.gitignore:14:/AGENTS.md`.
- `AI_WORKSPACE_GUIDE.md` remains ignored by
  `.gitignore:15:/AI_WORKSPACE_GUIDE.md`.

The command did not produce ignore evidence for absent or non-ignored directory
arguments such as `frontend/dist`, `github`, or `workspace_references` in this
worktree invocation; the source-boundary policy still forbids staging those
paths.

`git ls-files -ci --exclude-standard` returned no tracked ignored files.

## Scrub Results

Broad scrub command:

```powershell
rg -n --hidden --glob '!frontend/dist/**' --glob '!workspace_artifacts/**' --glob '!node_modules/**' --glob '!.venv-*/**' "C:\\Users|xiao|/Users/|workspace_artifacts|\.env|api[_-]?key|Authorization|Bearer|token|secret|password" <candidate paths>
```

Classification:

- Real local absolute path hits in candidate set: none. A narrower
  `C:\\Users|/Users/|xiao` scan returned no candidate hits.
- High-confidence secret regex hits: none. A stricter scan for OpenAI-style
  keys, GitHub/Slack/AWS/Google patterns, private-key headers, long bearer
  tokens, and long inline API-key assignments returned no matches.
- Fake fixture / redaction test hits:
  `test-key`, `bad-key`, `embedding-key`, `rerank-key`, `chat-key`,
  `sk-hidden`, `job_secret_123`, `session_secret_456`, and synthetic
  `Authorization: Bearer abcdefghij1234567890`.
- Expected source-code credential plumbing hits:
  environment variable names, masked API-key fields, safe header construction,
  and redaction/denylist code paths in routers, provider capability code, MCP
  source tools, generated OpenAPI, and generated TypeScript schemas.
- Expected runtime-output references:
  source-safe references to `workspace_artifacts` as output roots or path
  denial rules, not staged runtime contents.

Risk judgment:

- No high-confidence real secret was found in explicit candidate paths.
- Fixture/redaction hits are intentional deterministic tests or schema/code
  fields.
- `tests/live_api_chat_full_writing_chain_smoke.py` remains source-safe as a
  harness but must not be executed during staging-readiness because it resolves
  configured provider fields and sets `CHAT_API_KEY` in-process.

## JSON / JSONL Validation

Passed:

- `frontend/openapi/modular-pipeline-openapi.json`.
- `workspace_tests/evaluation_manifests/rerank_canary_dry_run_sample.json`.
- `workspace_tests/fixtures/wiki_eval_smoke/manifest.json`.
- `workspace_tests/evaluation_manifests/rerank_canary_qrels.jsonl`, 40 rows.
- `workspace_tests/evaluation_manifests/rerank_canary_queries.jsonl`, 30 rows.
- `docs/plans/longrun-goal-state-2026-06-19.json` also parsed successfully for
  local record consistency, but remains local-only by default.

## Diff / Whitespace Checks

Passed:

- `git diff --check -- <53 explicit candidate paths>`.
- `git diff --check -- docs/plans/scholar-ai-source-boundary-staging-readiness-2026-06-20.md docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md docs/plans/scholar-ai-reference-derived-code-plan-verification-audit-2026-06-20.md docs/plans/longrun-goal-state-2026-06-19.json`.
- `git ls-files -ci --exclude-standard` returned empty output.

## Focused Tests

Initial backend focused run:

- Command used source `.venv-1` from the current worktree root.
- Result: 20 failures, 114 passed.
- Cause: all failures were `403 Forbidden` with
  `local_api_capability_missing`, indicating the local API capability gate was
  enabled for TestClient routes.

Backend focused rerun:

```powershell
$env:LITASSIST_API_CAPABILITY_AUTH='0'
C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.venv-1\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_mcp_phase2_tool_loop.py tests\test_api_chat_local_literature_tool_use.py tests\test_api_probe_semantics.py tests\test_evidence_pack_build_contract.py tests\test_runtime_router_contract.py tests\test_writing_runtime_persistence.py tests\test_writing_submission_export.py tests\test_live_api_chat_full_writing_chain_smoke_harness.py agent_mcp_server\tests\test_source_tools.py -q
```

Result:

- `134 passed, 15 warnings in 15.26s`.
- Warnings were unknown pytest marks for persistence smoke/full labels.

Frontend focused run:

- `npm run test -- --run ...` from this worktree failed because `vitest` is not
  installed in this worktree.
- Directly invoking source-project
  `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\frontend\node_modules\.bin\vitest.cmd`
  from this worktree also failed because the worktree `vite.config.ts` imports
  `vitest` relative to this worktree and cannot resolve the package.
- No frontend dependency install or generated output mutation was performed.

Recorded frontend evidence still relevant:

- The prior residual-closure record reports focused frontend tests and full
  frontend suite passed in the source project/main worktree:
  `npm run test -- --run` passed `130 files / 804 tests`, and
  `npm run build` passed.
- Parent thread should rerun frontend focused/full suite after dependency
  availability is confirmed in the staging worktree or in the source project
  root before commit.

Parent source-root frontend rerun:

- Parent source root:
  `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script`.
- Command:
  `npm run test -- --run` from `frontend/`.
- Result:
  `130 passed` test files and `804 passed` tests.
- Non-fatal stderr:
  jsdom `AggregateError` output from `PdfReaderShell.test.tsx` during
  `debounces read-progress writes via setLastPage`; Vitest still exited 0 and
  all tests passed.
- Command:
  `npm run build` from `frontend/`.
- Result:
  TypeScript and Vite production build passed; generated output remains under
  ignored `frontend/dist/`.
- Mature references checked by the parent thread:
  Vitest CLI documentation for non-watch `vitest run` behavior and Vite build
  documentation for production build verification.

## Docs / Plans Boundary

The following files are visible for review but should not be included in public
source staging by default:

- `docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md`.
- `docs/plans/scholar-ai-reference-derived-code-plan-verification-audit-2026-06-20.md`.
- `docs/plans/longrun-goal-state-2026-06-19.json`.
- `docs/plans/scholar-ai-source-boundary-staging-readiness-2026-06-20.md`.
- `docs/plans/scholar-ai-pre-stage-dry-run-2026-06-20.md`.

Reason:

- These contain internal execution history, checkpoint ids, local paths, or
  agent review context.
- `SOURCE_RELEASE_POLICY.md` classifies internal plans/evidence under
  `docs/plans/` as local-only unless intentionally converted to public docs.

## Recommendation

Parent thread can enter the explicit path staging phase for the approved
candidate source/test/fixture paths, with these constraints:

1. Stage with explicit pathspecs only; do not use `git add .`.
2. Exclude `docs/plans/*`, `tools/longrun/*`, `workspace_artifacts/`, `.env*`,
   `AGENTS.md`, `AI_WORKSPACE_GUIDE.md`, `github/`,
   `workspace_references/`, `frontend/dist/`, DB/log/profile/cache files, and
   credential/runtime stores.
3. After staging, run `git diff --cached --check`,
   `git ls-files -ci --exclude-standard`, and inspect
   `git diff --cached --name-status`.
4. Frontend source-root dependency-complete verification has now passed in the
   parent thread; rerun it again only if files change before commit.
5. Real provider/API capability smoke has now passed separately as
   `passed_provider_tool_capability_probe`; full natural-prompt writing-chain
   acceptance remains out of scope for this dry-run.

## Remaining Decisions

- Whether any internal `docs/plans` evidence should be published after scrub,
  or remain local-only as policy defaults.
- Whether `tools/longrun/longrun-prompt.md` and local runbooks should be
  rewritten into public contributor documentation or remain private agent
  operations.
- Whether the source-safe live provider smoke harness should be included in the
  public test tree while full natural-prompt writing-chain acceptance remains
  out of scope for this dry-run.
- Whether selected `workspace_tests` fixtures are desirable public
  reproducibility assets or should remain local-only despite passing scrub.
