---
mode: agent
description: Squad coordinator startup self-check (DD5). Validates routing, agent file, chatmodes, prompt/skill split, owner profile, and HR1-6 documentation links. Surfaces Facts/Decision-needed/Evidence/Safe-next on any failure.
---

# Squad Doctor — Startup Self-Check

You are running the Squad coordinator startup self-check (Squad 0.9.3-modular, decision DD5).

Run **all 6 checks**, do not stop on first failure. Collect all failing items, then output a single structured report.

## Check 1 — Coordinator agent file

- Verify `.github/agents/squad.agent.md` exists.
- Verify the head of the file contains `version: 0.9.3-modular` (or higher).
- Verify it contains the section `## 协调者职责（中文摘要 · 通用模板）`.
- Verify it contains the long-run completion gate marker `长跑收口闸门（D11=B）`.

## Check 2 — Routing rules

- Verify `.squad/routing.md` exists.
- Verify it contains `Coordinator Auto-Routing Rules` (added 2026-04-27 by A-3).

## Check 3 — Chat modes harvested

- Verify `.github/chatmodes/` directory exists.
- Verify it contains at least one `*.chatmode.md` file.
- Sample one chatmode file and confirm its YAML frontmatter is well-formed (starts with `---`, closes with `---`).

## Check 4 — Owner profile (DD4)

- If `tools/squad/profile-version-check.ps1` exists, recommend running it (`pwsh -NoProfile -File tools/squad/profile-version-check.ps1`).
- If the script returns non-zero, treat as failure.
- If the script does not exist yet, treat as a SUGGESTION rather than a failure.

## Check 5 — Prompt and skill split (T5)

- Verify `.github/prompts/squad-plan.prompt.md` exists.
- Verify `.github/prompts/squad-doctor.prompt.md` exists.
- Verify `.github/prompts/squad-round.prompt.md` exists.
- Verify `.github/prompts/prompts.md` does not exist.
- Verify `.github/prompts/prompts.md.deprecated` exists and says not to add new instructions there.
- Verify `.github/skills/squad-startup-packet/SKILL.md` exists.
- Verify `.github/skills/squad-cli-handoff/SKILL.md` exists.

## Check 6 — HR1-6 documentation links

- Verify `CLAUDE.md` (repo root) contains keywords `HR1`, `HR2`, `HR3`, `HR4`, `HR5`, `HR6`.
- Verify `.squad/identity/start-here.md` exists (if present).
- Verify `.squad/tools/pool_append.py` exists (HR1 implementation anchor).
- Verify `.github/copilot-instructions.md` contains `D11=B 长跑收口闸门`.

## Output format

If **all checks pass**, output exactly:

```
SQUAD DOCTOR: OK (6/6 checks passed)
```

If **any check fails**, output a structured report:

```
SQUAD DOCTOR: FAIL (N/6 checks passed)

## Facts
- Check K (<title>): <what was observed>
...

## Decision needed
<the single most important coordinator decision the user needs to make to unblock startup>

## Evidence
- <file path> :: <line range or absence>
...

## Safe next action
<one concrete step the coordinator should take, or recommend to the user, before proceeding>
```

Do not enter any long-running mode, dispatch any subagent, or write any artifact until at least 5 of 6 checks pass and the user has acknowledged any remaining FAIL.
