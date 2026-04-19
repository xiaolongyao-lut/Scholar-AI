# Modular Pipeline Script Guidance

This file mirrors the repository's Copilot-wide instructions for Claude Code.

## Available Project Skills

Claude should prefer the project-local skills under `.claude/skills/` when a task matches a specialized workflow. Those skills were migrated from:

- `.github/skills/*`
- `.github/instructions/*.instructions.md`

Use the matching skill instead of re-deriving the same checklist or playbook in the main conversation.

## Repository-Wide Working Style

### 1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:

- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them; don't pick silently.
- If a simpler approach exists, say so.
- If something is unclear, stop and ask.

### 2. Simplicity First

Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No flexibility or configurability that was not requested.
- No defensive error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

Touch only what you must. Clean up only your own mess.

When editing existing code:

- Do not improve adjacent code, comments, or formatting unless requested.
- Do not refactor things that are not broken.
- Match existing style, even if you would do it differently.
- If you notice unrelated dead code, mention it; do not delete it.

When your changes create orphans:

- Remove imports, variables, and functions that your changes made unused.
- Do not remove pre-existing dead code unless asked.

Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

Define success criteria. Loop until verified.

Transform tasks into verifiable goals:

- "Add validation" becomes "Write tests for invalid inputs, then make them pass"
- "Fix the bug" becomes "Write a test that reproduces it, then make it pass"
- "Refactor X" becomes "Ensure tests pass before and after"

For multi-step tasks, keep a brief plan:

1. Step -> verify with a concrete check
2. Step -> verify with a concrete check
3. Step -> verify with a concrete check

Strong success criteria let you continue independently. Weak criteria require repeated clarification.
